from __future__ import annotations

import json
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from aiwf.models import ask_model
from aiwf.tasks import refresh_tasks, tail_log


@dataclass
class ReviewResult:
    done: bool
    summary: str
    next_steps: list[str]
    raw: str


def _run_shell(cmd: str) -> str:
    try:
        proc = subprocess.run(
            ["bash", "-lc", cmd],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return ""
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if out and err:
        return f"{out}\n\n[stderr]\n{err}"
    return out or err


def gather_git_context(max_chars: int = 6000) -> str:
    status = _run_shell("git status -sb")
    diff = _run_shell("git diff -- .")
    staged = _run_shell("git diff --cached -- .")

    chunks = [
        "[git_status]\n" + (status or "(empty)"),
        "[git_diff]\n" + (diff or "(empty)"),
        "[git_staged_diff]\n" + (staged or "(empty)"),
    ]
    merged = "\n\n".join(chunks)
    if len(merged) <= max_chars:
        return merged
    return merged[:max_chars] + "\n\n[truncated]"


def gather_task_context(conn: sqlite3.Connection, task_id: int, log_lines: int = 120) -> str:
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
        raise RuntimeError(f"任务不存在: {task_id}")

    lines = [
        f"id: {row['id']}",
        f"name: {row['name']}",
        f"status: {row['status']}",
        f"pid: {row['pid']}",
        f"started_at: {row['started_at']}",
        f"finished_at: {row['finished_at']}",
        f"exit_code: {row['exit_code']}",
        f"cmd: {row['cmd']}",
    ]
    log_text = ""
    if row["log_path"]:
        log_text = tail_log(str(row["log_path"]), lines=log_lines)
    return "[task]\n" + "\n".join(lines) + "\n\n[task_log_tail]\n" + (log_text or "(empty)")


def _parse_review_json(raw: str) -> ReviewResult:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0 or end < start:
        return ReviewResult(done=False, summary=raw.strip(), next_steps=[], raw=raw)

    body = text[start : end + 1]
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return ReviewResult(done=False, summary=raw.strip(), next_steps=[], raw=raw)

    done = bool(payload.get("done", False))
    summary = str(payload.get("summary", "")).strip() or raw.strip()
    next_steps_raw = payload.get("next_steps", [])
    next_steps: list[str] = []
    if isinstance(next_steps_raw, list):
        next_steps = [str(x).strip() for x in next_steps_raw if str(x).strip()]
    return ReviewResult(done=done, summary=summary, next_steps=next_steps, raw=raw)


def review_once(
    cfg: dict,
    goal: str,
    profile: str,
    provider: str | None,
    model: str | None,
    code_context: str,
    task_context: str,
) -> ReviewResult:
    prompt = (
        "你是任务完成监督器。请根据目标和上下文判断任务是否已完成。\n"
        "严格输出 JSON，不要输出任何额外文本，格式如下：\n"
        '{"done": true/false, "summary": "一句话总结", "next_steps": ["步骤1", "步骤2"]}\n\n'
        f"目标:\n{goal}\n\n"
        f"{code_context}\n\n"
        f"{task_context}\n"
    )
    raw = ask_model(
        cfg,
        prompt=prompt,
        profile=profile,
        provider_override=provider,
        model_override=model,
    )
    return _parse_review_json(raw)


def review_loop(
    conn: sqlite3.Connection,
    cfg: dict,
    goal: str,
    profile: str,
    provider: str | None,
    model: str | None,
    interval_sec: int,
    max_rounds: int,
    task_id: int | None,
    log_lines: int,
    max_code_chars: int,
    on_round: Callable[[int, ReviewResult], None] | None = None,
) -> tuple[bool, list[ReviewResult]]:
    history: list[ReviewResult] = []
    for _round in range(1, max_rounds + 1):
        code_ctx = gather_git_context(max_chars=max_code_chars)
        task_ctx = ""
        if task_id is not None:
            task_ctx = gather_task_context(conn, task_id=task_id, log_lines=log_lines)
        result = review_once(
            cfg=cfg,
            goal=goal,
            profile=profile,
            provider=provider,
            model=model,
            code_context=code_ctx,
            task_context=task_ctx,
        )
        history.append(result)
        if on_round is not None:
            on_round(_round, result)
        if result.done:
            return True, history
        if _round < max_rounds:
            time.sleep(max(1, interval_sec))
    return False, history
