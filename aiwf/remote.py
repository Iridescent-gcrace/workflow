from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from aiwf.db import connect_db, init_db
from aiwf.tasks import refresh_tasks, start_task, tail_log


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _unauthorized(handler: BaseHTTPRequestHandler) -> None:
    handler.send_response(401)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.end_headers()
    handler.wfile.write(_json_bytes({"ok": False, "error": "unauthorized"}))


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8", errors="replace")
    if not raw.strip():
        return {}
    return json.loads(raw)


def _run_aiwf(args: list[str], timeout_sec: int = 180) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "aiwf", *args]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def serve_remote(host: str, port: int, token: str) -> None:
    class Handler(BaseHTTPRequestHandler):
        server_version = "AIWFRemote/0.1"

        def _auth_ok(self) -> bool:
            auth = self.headers.get("Authorization", "")
            if auth == f"Bearer {token}":
                return True
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            query_token = (qs.get("token") or [""])[0]
            return bool(query_token and query_token == token)

        def _send_json(self, code: int, payload: dict[str, Any]) -> None:
            body = _json_bytes(payload)
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if not self._auth_ok():
                _unauthorized(self)
                return
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/health":
                self._send_json(200, {"ok": True, "service": "aiwf-remote"})
                return
            if path == "/status":
                result = _run_aiwf(["status"])
                self._send_json(200, result)
                return
            if path == "/tasks":
                conn = connect_db()
                init_db(conn)
                refresh_tasks(conn)
                rows = conn.execute(
                    """
                    SELECT id, name, status, pid, started_at, finished_at, exit_code
                    FROM tasks
                    ORDER BY id DESC
                    LIMIT 30
                    """
                ).fetchall()
                conn.close()
                items = [dict(r) for r in rows]
                self._send_json(200, {"ok": True, "tasks": items})
                return
            if path.startswith("/tasks/"):
                raw_id = path.split("/")[-1]
                try:
                    task_id = int(raw_id)
                except ValueError:
                    self._send_json(400, {"ok": False, "error": "invalid task id"})
                    return
                conn = connect_db()
                init_db(conn)
                refresh_tasks(conn)
                row = conn.execute(
                    """
                    SELECT id, name, cmd, status, pid, started_at, finished_at, exit_code, log_path
                    FROM tasks
                    WHERE id = ?
                    """,
                    (task_id,),
                ).fetchone()
                if row is None:
                    conn.close()
                    self._send_json(404, {"ok": False, "error": "task not found"})
                    return
                task = dict(row)
                if task.get("log_path"):
                    task["log_tail"] = tail_log(str(task["log_path"]), lines=80)
                conn.close()
                self._send_json(200, {"ok": True, "task": task})
                return
            self._send_json(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._auth_ok():
                _unauthorized(self)
                return

            parsed = urlparse(self.path)
            path = parsed.path
            try:
                body = _read_json_body(self)
            except json.JSONDecodeError:
                self._send_json(400, {"ok": False, "error": "invalid json body"})
                return

            if path == "/ask":
                prompt = str(body.get("prompt", "")).strip()
                if not prompt:
                    self._send_json(400, {"ok": False, "error": "prompt required"})
                    return
                profile = str(body.get("profile", "fast")).strip() or "fast"
                result = _run_aiwf(["q", prompt, "--profile", profile], timeout_sec=240)
                self._send_json(200, result)
                return

            if path == "/run":
                args = body.get("args", [])
                if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
                    self._send_json(400, {"ok": False, "error": "args must be list[str]"})
                    return
                if not args:
                    self._send_json(400, {"ok": False, "error": "args required"})
                    return
                allowed_first = {
                    "status",
                    "st",
                    "q",
                    "ask",
                    "j",
                    "task",
                    "k",
                    "tip",
                    "p",
                    "paper",
                    "x",
                    "capture",
                    "c",
                    "rv",
                    "review",
                }
                if args[0] not in allowed_first:
                    self._send_json(403, {"ok": False, "error": f"command not allowed: {args[0]}"})
                    return
                result = _run_aiwf(args, timeout_sec=300)
                self._send_json(200, result)
                return

            if path == "/tasks":
                name = str(body.get("name", "")).strip()
                cmd = str(body.get("cmd", "")).strip()
                if not name or not cmd:
                    self._send_json(400, {"ok": False, "error": "name and cmd are required"})
                    return
                conn = connect_db()
                init_db(conn)
                task_id, pid, log_path = start_task(conn, name=name, cmd=cmd)
                conn.close()
                self._send_json(200, {"ok": True, "id": task_id, "pid": pid, "log_path": str(log_path)})
                return

            self._send_json(404, {"ok": False, "error": "not found"})

        def log_message(self, fmt: str, *args: Any) -> None:
            # Keep terminal clean; remote logs are query-based.
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"AIWF remote server running on http://{host}:{port}")
    print("Use header: Authorization: Bearer <token>")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

