from __future__ import annotations

import errno
import os
import shlex
import sqlite3
import subprocess
from collections import deque
from pathlib import Path

from aiwf.config import LOG_DIR, ensure_app_dirs
from aiwf.db import utc_now


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        return exc.errno == errno.EPERM
    return True


def start_task(conn: sqlite3.Connection, name: str, cmd: str) -> tuple[int, int, Path]:
    ensure_app_dirs()
    cur = conn.cursor()
    started_at = utc_now()
    cur.execute(
        "INSERT INTO tasks (name, cmd, status, started_at) VALUES (?, ?, ?, ?)",
        (name, cmd, "starting", started_at),
    )
    task_id = int(cur.lastrowid)

    log_path = LOG_DIR / f"task-{task_id}.log"
    exit_file = LOG_DIR / f"task-{task_id}.exit"
    wrapper = f"{cmd}; __aiwf_code=$?; printf '%s' \"$__aiwf_code\" > {shlex.quote(str(exit_file))}"

    with log_path.open("ab") as logf:
        proc = subprocess.Popen(  # noqa: S602
            ["bash", "-lc", wrapper],
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    cur.execute(
        "UPDATE tasks SET pid = ?, status = ?, log_path = ?, exit_file = ? WHERE id = ?",
        (proc.pid, "running", str(log_path), str(exit_file), task_id),
    )
    conn.commit()
    return task_id, int(proc.pid), log_path


def refresh_tasks(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT id, pid, status, exit_file FROM tasks WHERE status IN ('starting', 'running')"
    ).fetchall()
    updated = 0
    for row in rows:
        task_id = int(row["id"])
        pid = int(row["pid"] or 0)
        exit_file = str(row["exit_file"] or "")
        if exit_file and Path(exit_file).exists():
            raw = Path(exit_file).read_text(encoding="utf-8").strip()
            try:
                code = int(raw)
            except ValueError:
                code = -1
            status = "done" if code == 0 else "failed"
            conn.execute(
                "UPDATE tasks SET status = ?, finished_at = ?, exit_code = ? WHERE id = ?",
                (status, utc_now(), code, task_id),
            )
            updated += 1
            continue

        if pid and not _pid_exists(pid):
            conn.execute(
                "UPDATE tasks SET status = ?, finished_at = ? WHERE id = ?",
                ("lost", utc_now(), task_id),
            )
            updated += 1

    conn.commit()
    return updated


def tail_log(path: str, lines: int = 80) -> str:
    p = Path(path)
    if not p.exists():
        return f"[log 不存在] {path}"
    buf: deque[str] = deque(maxlen=lines)
    with p.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            buf.append(line.rstrip("\n"))
    return "\n".join(buf)

