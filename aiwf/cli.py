from __future__ import annotations

import argparse
import secrets
import sqlite3
import sys

from aiwf.capture import read_clipboard, write_note_markdown
from aiwf.config import APP_DIR, CONFIG_PATH, DB_PATH, LOG_DIR, NOTES_DIR, load_config, save_config
from aiwf.db import connect_db, init_db, utc_now
from aiwf.models import ModelError, ask_model
from aiwf.papers import fetch_arxiv_entry
from aiwf.remote import serve_remote
from aiwf.review import gather_git_context, gather_task_context, review_loop, review_once
from aiwf.tasks import refresh_tasks, start_task, tail_log
from aiwf.utils import auto_title, normalize_tags, read_text


def _pick_content(args: argparse.Namespace) -> tuple[str, str]:
    if getattr(args, "content", None):
        return str(args.content), "manual"
    if getattr(args, "file", None):
        return read_text(str(args.file)), f"file:{args.file}"
    if getattr(args, "clipboard", False):
        return read_clipboard(), "clipboard"
    if not sys.stdin.isatty():
        return sys.stdin.read(), "stdin"
    raise RuntimeError("缺少内容来源：请使用 --content / --file / --clipboard，或通过管道输入。")


def _print_rows(rows: list[sqlite3.Row], columns: list[str]) -> None:
    if not rows:
        print("暂无数据")
        return
    widths = {c: len(c) for c in columns}
    for row in rows:
        for c in columns:
            widths[c] = max(widths[c], len(str(row[c] if row[c] is not None else "")))
    header = " | ".join(c.ljust(widths[c]) for c in columns)
    print(header)
    print("-+-".join("-" * widths[c] for c in columns))
    for row in rows:
        print(" | ".join(str(row[c] if row[c] is not None else "").ljust(widths[c]) for c in columns))


def cmd_init(_: argparse.Namespace, cfg: dict, conn: sqlite3.Connection) -> int:
    init_db(conn)
    save_config(cfg)
    print(f"AIWF 初始化完成")
    print(f"APP: {APP_DIR}")
    print(f"CONFIG: {CONFIG_PATH}")
    print(f"DB: {DB_PATH}")
    print(f"LOGS: {LOG_DIR}")
    print(f"NOTES: {NOTES_DIR}")
    return 0


def cmd_tip_add(args: argparse.Namespace, _: dict, conn: sqlite3.Connection) -> int:
    tags = normalize_tags(args.tags)
    conn.execute(
        "INSERT INTO tips (title, content, tags, created_at) VALUES (?, ?, ?, ?)",
        (args.title.strip(), args.content.strip(), tags, utc_now()),
    )
    conn.commit()
    print("tip 已保存")
    return 0


def cmd_tip_list(args: argparse.Namespace, _: dict, conn: sqlite3.Connection) -> int:
    if args.tag:
        rows = conn.execute(
            "SELECT id, title, tags, created_at FROM tips WHERE tags LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{args.tag.lower()}%", args.limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, title, tags, created_at FROM tips ORDER BY id DESC LIMIT ?",
            (args.limit,),
        ).fetchall()
    _print_rows(rows, ["id", "title", "tags", "created_at"])
    return 0


def _generate_capture_note(
    cfg: dict,
    content: str,
    profile: str,
    provider: str | None,
    model: str | None,
) -> str:
    prompt = (
        "你是知识管理助手。请把下面内容整理成可复用的笔记，输出结构：\n"
        "1) 主题\n2) 关键洞察（3-5条）\n3) 可执行动作（2-3条）\n4) 可复用提示词模板\n\n"
        "内容如下：\n"
        f"{content}"
    )
    return ask_model(cfg, prompt=prompt, profile=profile, provider_override=provider, model_override=model)


def _save_capture(
    conn: sqlite3.Connection,
    source: str,
    title: str,
    content: str,
    tags: str,
    note: str,
    note_path: str,
) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO captures (source, title, content, tags, note, note_path, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (source, title, content, tags, note, note_path, utc_now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def cmd_capture_add(args: argparse.Namespace, cfg: dict, conn: sqlite3.Connection) -> int:
    content, source = _pick_content(args)
    content = content.strip()
    if not content:
        raise RuntimeError("内容为空，无法沉淀。")
    title = args.title.strip() if args.title else auto_title(content)
    tags = normalize_tags(args.tags)

    note = ""
    note_path = ""
    if args.auto_note:
        note = _generate_capture_note(cfg, content, args.profile, args.provider, args.model)
        note_file = write_note_markdown(title=title, raw_content=content, note=note)
        note_path = str(note_file)

    capture_id = _save_capture(conn, source, title, content, tags, note, note_path)
    print(f"capture 已保存: id={capture_id}, title={title}")
    if note_path:
        print(f"笔记文件: {note_path}")
    return 0


def cmd_capture_quick(args: argparse.Namespace, cfg: dict, conn: sqlite3.Connection) -> int:
    content = read_clipboard().strip()
    if not content:
        raise RuntimeError("剪贴板为空，无法一键沉淀。")
    title = args.title.strip() if args.title else auto_title(content)
    tags = normalize_tags(args.tags)

    note = ""
    note_path = ""
    if not args.no_note:
        note = _generate_capture_note(cfg, content, args.profile, args.provider, args.model)
        note_file = write_note_markdown(title=title, raw_content=content, note=note)
        note_path = str(note_file)

    capture_id = _save_capture(conn, "quick-clipboard", title, content, tags, note, note_path)
    print(f"quick capture 完成: id={capture_id}, title={title}")
    if note_path:
        print(f"笔记文件: {note_path}")
    return 0


def cmd_capture_list(args: argparse.Namespace, _: dict, conn: sqlite3.Connection) -> int:
    if args.tag:
        rows = conn.execute(
            """
            SELECT id, title, source, tags, created_at
            FROM captures
            WHERE tags LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (f"%{args.tag.lower()}%", args.limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, title, source, tags, created_at
            FROM captures
            ORDER BY id DESC
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()
    _print_rows(rows, ["id", "title", "source", "tags", "created_at"])
    return 0


def cmd_capture_show(args: argparse.Namespace, _: dict, conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT id, title, source, tags, content, note, note_path, created_at FROM captures WHERE id = ?",
        (args.id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"capture 不存在: {args.id}")
    print(f"id: {row['id']}")
    print(f"title: {row['title']}")
    print(f"source: {row['source']}")
    print(f"tags: {row['tags']}")
    print(f"created_at: {row['created_at']}")
    print("\n[content]\n")
    print(row["content"])
    if row["note"]:
        print("\n[note]\n")
        print(row["note"])
    if row["note_path"]:
        print(f"\n[note_file]\n{row['note_path']}")
    return 0


def cmd_ask(args: argparse.Namespace, cfg: dict, _: sqlite3.Connection) -> int:
    output = ask_model(
        cfg,
        prompt=args.prompt,
        profile=args.profile,
        provider_override=args.provider,
        model_override=args.model,
    )
    print(output)
    return 0


def cmd_profile_list(_: argparse.Namespace, cfg: dict, __: sqlite3.Connection) -> int:
    rows = []
    for name, profile in cfg.get("profiles", {}).items():
        rows.append(
            {
                "name": name,
                "provider": str(profile.get("provider", "")),
                "model": str(profile.get("model", "")),
            }
        )
    if not rows:
        print("暂无 profile")
        return 0
    max_name = max(len("name"), max(len(r["name"]) for r in rows))
    max_provider = max(len("provider"), max(len(r["provider"]) for r in rows))
    print(f"{'name'.ljust(max_name)} | {'provider'.ljust(max_provider)} | model")
    print(f"{'-' * max_name}-+-{'-' * max_provider}-+-{'-' * 20}")
    for row in rows:
        print(f"{row['name'].ljust(max_name)} | {row['provider'].ljust(max_provider)} | {row['model']}")
    return 0


def cmd_profile_set(args: argparse.Namespace, cfg: dict, __: sqlite3.Connection) -> int:
    cfg.setdefault("profiles", {})
    cfg["profiles"][args.name] = {"provider": args.provider, "model": args.model}
    save_config(cfg)
    print(f"profile 已更新: {args.name} -> {args.provider}/{args.model}")
    return 0


def cmd_task_start(args: argparse.Namespace, _: dict, conn: sqlite3.Connection) -> int:
    task_id, pid, log_path = start_task(conn, name=args.name, cmd=args.cmd)
    print(f"任务已启动: id={task_id}, pid={pid}")
    print(f"log: {log_path}")
    return 0


def cmd_task_refresh(_: argparse.Namespace, __: dict, conn: sqlite3.Connection) -> int:
    updated = refresh_tasks(conn)
    print(f"已刷新任务状态: {updated} 条更新")
    return 0


def cmd_task_list(_: argparse.Namespace, __: dict, conn: sqlite3.Connection) -> int:
    refresh_tasks(conn)
    rows = conn.execute(
        """
        SELECT id, name, status, pid, started_at, finished_at, exit_code
        FROM tasks
        ORDER BY id DESC
        LIMIT 100
        """
    ).fetchall()
    _print_rows(rows, ["id", "name", "status", "pid", "started_at", "finished_at", "exit_code"])
    return 0


def cmd_task_logs(args: argparse.Namespace, _: dict, conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT log_path FROM tasks WHERE id = ?", (args.id,)).fetchone()
    if row is None:
        raise RuntimeError(f"任务不存在: {args.id}")
    log_path = str(row["log_path"] or "")
    if not log_path:
        raise RuntimeError(f"任务还没有日志文件: {args.id}")
    print(tail_log(log_path, lines=args.lines))
    return 0


def cmd_paper_add(args: argparse.Namespace, _: dict, conn: sqlite3.Connection) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO papers (source, ref, title, url, abstract, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("manual", "", args.title.strip(), args.url.strip(), (args.abstract or "").strip(), utc_now()),
    )
    conn.commit()
    print(f"paper 已添加: id={cur.lastrowid}")
    return 0


def cmd_paper_arxiv(args: argparse.Namespace, _: dict, conn: sqlite3.Connection) -> int:
    info = fetch_arxiv_entry(args.id)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO papers (source, ref, title, url, abstract, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("arxiv", args.id.strip(), info["title"], info["url"], info["abstract"], utc_now()),
    )
    conn.commit()
    print(f"arXiv 已导入: id={cur.lastrowid}")
    print(f"title: {info['title']}")
    return 0


def cmd_paper_list(args: argparse.Namespace, _: dict, conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT id, source, ref, title, created_at FROM papers ORDER BY id DESC LIMIT ?",
        (args.limit,),
    ).fetchall()
    _print_rows(rows, ["id", "source", "ref", "title", "created_at"])
    return 0


def cmd_paper_summarize(args: argparse.Namespace, cfg: dict, conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id, title, abstract FROM papers WHERE id = ?", (args.id,)).fetchone()
    if row is None:
        raise RuntimeError(f"paper 不存在: {args.id}")
    abstract = str(row["abstract"] or "").strip()
    if not abstract:
        raise RuntimeError("paper 缺少 abstract，暂无法总结。可先用 `paper add --abstract` 或 `paper arxiv` 导入。")
    prompt = (
        "请基于以下论文摘要输出：\n"
        "1) 研究问题\n2) 核心方法\n3) 主要结论\n4) 局限性\n5) 我下一步该如何实践（3条）\n\n"
        f"标题: {row['title']}\n摘要: {abstract}"
    )
    summary = ask_model(
        cfg,
        prompt=prompt,
        profile=args.profile,
        provider_override=args.provider,
        model_override=args.model,
    )
    conn.execute("UPDATE papers SET summary = ? WHERE id = ?", (summary, args.id))
    conn.commit()
    print(summary)
    return 0


def cmd_status(_: argparse.Namespace, __: dict, conn: sqlite3.Connection) -> int:
    refresh_tasks(conn)
    tips_count = conn.execute("SELECT COUNT(*) FROM tips").fetchone()[0]
    captures_count = conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
    papers_count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    running = conn.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('starting', 'running')").fetchone()[0]
    print(f"tips: {tips_count}")
    print(f"captures: {captures_count}")
    print(f"papers: {papers_count}")
    print(f"running_tasks: {running}")
    return 0


def cmd_dash(args: argparse.Namespace, __: dict, conn: sqlite3.Connection) -> int:
    refresh_tasks(conn)
    tips_count = conn.execute("SELECT COUNT(*) FROM tips").fetchone()[0]
    captures_count = conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
    papers_count = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    running = conn.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('starting', 'running')").fetchone()[0]
    print("[summary]")
    print(f"tips={tips_count} captures={captures_count} papers={papers_count} running_tasks={running}")

    task_rows = conn.execute(
        """
        SELECT id, name, status, started_at
        FROM tasks
        ORDER BY id DESC
        LIMIT ?
        """,
        (args.limit,),
    ).fetchall()
    print("\n[latest_tasks]")
    _print_rows(task_rows, ["id", "name", "status", "started_at"])

    capture_rows = conn.execute(
        """
        SELECT id, title, tags, created_at
        FROM captures
        ORDER BY id DESC
        LIMIT ?
        """,
        (args.limit,),
    ).fetchall()
    print("\n[latest_captures]")
    _print_rows(capture_rows, ["id", "title", "tags", "created_at"])
    return 0


def _print_review_result(round_num: int, total: int, done: bool, summary: str, next_steps: list[str]) -> None:
    print(f"[round {round_num}/{total}] done={done}")
    print(f"summary: {summary}")
    if next_steps:
        print("next_steps:")
        for item in next_steps:
            print(f"- {item}")
    print()


def cmd_review_now(args: argparse.Namespace, cfg: dict, conn: sqlite3.Connection) -> int:
    code_ctx = ""
    if not args.no_code:
        code_ctx = gather_git_context(max_chars=args.max_code_chars)
    task_ctx = ""
    if args.task_id:
        task_ctx = gather_task_context(conn, task_id=args.task_id, log_lines=args.task_log_lines)

    if not code_ctx and not task_ctx:
        raise RuntimeError("没有可审查上下文。请移除 --no-code 或添加 --task-id。")

    result = review_once(
        cfg=cfg,
        goal=args.goal,
        profile=args.profile,
        provider=args.provider,
        model=args.model,
        code_context=code_ctx,
        task_context=task_ctx,
    )
    _print_review_result(1, 1, result.done, result.summary, result.next_steps)
    if args.raw:
        print("[raw]")
        print(result.raw)
    return 0


def cmd_review_loop(args: argparse.Namespace, cfg: dict, conn: sqlite3.Connection) -> int:
    def on_round(i: int, result) -> None:  # type: ignore[no-untyped-def]
        _print_review_result(i, args.max_rounds, result.done, result.summary, result.next_steps)

    done, history = review_loop(
        conn=conn,
        cfg=cfg,
        goal=args.goal,
        profile=args.profile,
        provider=args.provider,
        model=args.model,
        interval_sec=args.interval,
        max_rounds=args.max_rounds,
        task_id=args.task_id or None,
        log_lines=args.task_log_lines,
        max_code_chars=args.max_code_chars,
        on_round=on_round,
    )
    if done:
        print("review_loop 结论: 已完成")
        return 0
    if history:
        print("review_loop 结论: 未完成（达到最大轮询次数）")
    else:
        print("review_loop 未执行")
    return 3


def cmd_remote_token(args: argparse.Namespace, cfg: dict, __: sqlite3.Connection) -> int:
    token = secrets.token_urlsafe(max(16, args.bytes))
    print(token)
    if args.save:
        cfg.setdefault("remote", {})
        cfg["remote"]["token"] = token
        save_config(cfg)
        print("token 已写入配置")
    return 0


def cmd_remote_serve(args: argparse.Namespace, cfg: dict, __: sqlite3.Connection) -> int:
    token = args.token.strip() if args.token else str(cfg.get("remote", {}).get("token", "")).strip()
    if not token:
        raise RuntimeError("缺少 token。请使用 `wf rm t --save` 生成并保存，或在 `wf rm s --token ...` 传入。")
    serve_remote(host=args.host, port=args.port, token=token)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aiwf",
        description="All-in-one AI workflow terminal: capture, multi-model, task monitor, paper pipeline.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", aliases=["i"], help="初始化目录和数据库")
    p_init.set_defaults(func=cmd_init)

    p_tip = sub.add_parser("tip", aliases=["k"], help="AI 使用技巧")
    tip_sub = p_tip.add_subparsers(dest="tip_cmd", required=True)
    p_tip_add = tip_sub.add_parser("add", aliases=["a"], help="新增技巧")
    p_tip_add.add_argument("--title", required=True)
    p_tip_add.add_argument("--content", required=True)
    p_tip_add.add_argument("--tags", default="")
    p_tip_add.set_defaults(func=cmd_tip_add)

    p_tip_list = tip_sub.add_parser("list", aliases=["l"], help="查看技巧")
    p_tip_list.add_argument("--tag", default="")
    p_tip_list.add_argument("--limit", type=int, default=50)
    p_tip_list.set_defaults(func=cmd_tip_list)

    p_capture = sub.add_parser("capture", aliases=["c"], help="沉淀高价值对话")
    capture_sub = p_capture.add_subparsers(dest="capture_cmd", required=True)

    p_capture_add = capture_sub.add_parser("add", aliases=["a"], help="添加沉淀内容")
    p_capture_add.add_argument("--title", default="")
    p_capture_add.add_argument("--content", default="")
    p_capture_add.add_argument("--file", default="")
    p_capture_add.add_argument("--clipboard", action="store_true")
    p_capture_add.add_argument("--tags", default="")
    p_capture_add.add_argument("--auto-note", action="store_true")
    p_capture_add.add_argument("--profile", default="deep")
    p_capture_add.add_argument("--provider", default="")
    p_capture_add.add_argument("--model", default="")
    p_capture_add.set_defaults(func=cmd_capture_add)

    p_capture_quick = capture_sub.add_parser("quick", aliases=["q"], help="一键沉淀（剪贴板）")
    p_capture_quick.add_argument("--title", default="")
    p_capture_quick.add_argument("--tags", default="")
    p_capture_quick.add_argument("--no-note", action="store_true")
    p_capture_quick.add_argument("--profile", default="deep")
    p_capture_quick.add_argument("--provider", default="")
    p_capture_quick.add_argument("--model", default="")
    p_capture_quick.set_defaults(func=cmd_capture_quick)

    p_capture_list = capture_sub.add_parser("list", aliases=["l"], help="查看沉淀列表")
    p_capture_list.add_argument("--tag", default="")
    p_capture_list.add_argument("--limit", type=int, default=50)
    p_capture_list.set_defaults(func=cmd_capture_list)

    p_capture_show = capture_sub.add_parser("show", aliases=["s"], help="查看沉淀详情")
    p_capture_show.add_argument("id", type=int)
    p_capture_show.set_defaults(func=cmd_capture_show)

    p_capture_fast = sub.add_parser("x", help="一键沉淀（剪贴板，短命令）")
    p_capture_fast.add_argument("--title", default="")
    p_capture_fast.add_argument("--tags", default="")
    p_capture_fast.add_argument("--no-note", action="store_true")
    p_capture_fast.add_argument("--profile", default="deep")
    p_capture_fast.add_argument("--provider", default="")
    p_capture_fast.add_argument("--model", default="")
    p_capture_fast.set_defaults(func=cmd_capture_quick)

    p_ask = sub.add_parser("ask", aliases=["q"], help="调用模型问答")
    p_ask.add_argument("prompt")
    p_ask.add_argument("--profile", default="fast")
    p_ask.add_argument("--provider", default="")
    p_ask.add_argument("--model", default="")
    p_ask.set_defaults(func=cmd_ask)

    p_profile = sub.add_parser("profile", aliases=["m"], help="管理模型路由")
    profile_sub = p_profile.add_subparsers(dest="profile_cmd", required=True)

    p_profile_list = profile_sub.add_parser("list", aliases=["l"], help="列出 profile")
    p_profile_list.set_defaults(func=cmd_profile_list)

    p_profile_set = profile_sub.add_parser("set", aliases=["s"], help="设置 profile")
    p_profile_set.add_argument("name")
    p_profile_set.add_argument("--provider", required=True)
    p_profile_set.add_argument("--model", required=True)
    p_profile_set.set_defaults(func=cmd_profile_set)

    p_task = sub.add_parser("task", aliases=["j"], help="慢任务监控")
    task_sub = p_task.add_subparsers(dest="task_cmd", required=True)

    p_task_start = task_sub.add_parser("start", aliases=["s"], help="启动后台任务")
    p_task_start.add_argument("--name", required=True)
    p_task_start.add_argument("--cmd", required=True)
    p_task_start.set_defaults(func=cmd_task_start)

    p_task_list = task_sub.add_parser("list", aliases=["l"], help="查看任务列表")
    p_task_list.set_defaults(func=cmd_task_list)

    p_task_refresh = task_sub.add_parser("refresh", aliases=["r"], help="刷新任务状态")
    p_task_refresh.set_defaults(func=cmd_task_refresh)

    p_task_logs = task_sub.add_parser("logs", aliases=["g"], help="查看任务日志")
    p_task_logs.add_argument("id", type=int)
    p_task_logs.add_argument("--lines", type=int, default=80)
    p_task_logs.set_defaults(func=cmd_task_logs)

    p_paper = sub.add_parser("paper", aliases=["p"], help="论文工作流入口")
    paper_sub = p_paper.add_subparsers(dest="paper_cmd", required=True)

    p_paper_add = paper_sub.add_parser("add", aliases=["a"], help="手动添加论文")
    p_paper_add.add_argument("--title", required=True)
    p_paper_add.add_argument("--url", default="")
    p_paper_add.add_argument("--abstract", default="")
    p_paper_add.set_defaults(func=cmd_paper_add)

    p_paper_arxiv = paper_sub.add_parser("arxiv", aliases=["x"], help="导入 arXiv 论文")
    p_paper_arxiv.add_argument("--id", required=True)
    p_paper_arxiv.set_defaults(func=cmd_paper_arxiv)

    p_paper_list = paper_sub.add_parser("list", aliases=["l"], help="查看论文列表")
    p_paper_list.add_argument("--limit", type=int, default=50)
    p_paper_list.set_defaults(func=cmd_paper_list)

    p_paper_summary = paper_sub.add_parser("summarize", aliases=["s"], help="总结论文摘要")
    p_paper_summary.add_argument("id", type=int)
    p_paper_summary.add_argument("--profile", default="deep")
    p_paper_summary.add_argument("--provider", default="")
    p_paper_summary.add_argument("--model", default="")
    p_paper_summary.set_defaults(func=cmd_paper_summarize)

    p_review = sub.add_parser("review", aliases=["rv"], help="AI 代码/任务审查")
    review_sub = p_review.add_subparsers(dest="review_cmd", required=True)

    p_review_now = review_sub.add_parser("now", aliases=["n"], help="执行一次 AI 审查")
    p_review_now.add_argument("--goal", required=True)
    p_review_now.add_argument("--task-id", type=int, default=0)
    p_review_now.add_argument("--task-log-lines", type=int, default=120)
    p_review_now.add_argument("--no-code", action="store_true")
    p_review_now.add_argument("--max-code-chars", type=int, default=6000)
    p_review_now.add_argument("--profile", default="deep")
    p_review_now.add_argument("--provider", default="")
    p_review_now.add_argument("--model", default="")
    p_review_now.add_argument("--raw", action="store_true")
    p_review_now.set_defaults(func=cmd_review_now)

    p_review_loop = review_sub.add_parser("loop", aliases=["l"], help="持续轮询 AI 直到完成或超时")
    p_review_loop.add_argument("--goal", required=True)
    p_review_loop.add_argument("--task-id", type=int, default=0)
    p_review_loop.add_argument("--task-log-lines", type=int, default=120)
    p_review_loop.add_argument("--max-code-chars", type=int, default=6000)
    p_review_loop.add_argument("--profile", default="deep")
    p_review_loop.add_argument("--provider", default="")
    p_review_loop.add_argument("--model", default="")
    p_review_loop.add_argument("--interval", type=int, default=60)
    p_review_loop.add_argument("--max-rounds", type=int, default=10)
    p_review_loop.set_defaults(func=cmd_review_loop)

    p_remote = sub.add_parser("remote", aliases=["rm"], help="手机远程访问 API")
    remote_sub = p_remote.add_subparsers(dest="remote_cmd", required=True)

    p_remote_token = remote_sub.add_parser("token", aliases=["t"], help="生成远程 token")
    p_remote_token.add_argument("--bytes", type=int, default=24)
    p_remote_token.add_argument("--save", action="store_true")
    p_remote_token.set_defaults(func=cmd_remote_token)

    p_remote_serve = remote_sub.add_parser("serve", aliases=["s"], help="启动远程服务")
    p_remote_serve.add_argument("--host", default="0.0.0.0")
    p_remote_serve.add_argument("--port", type=int, default=8787)
    p_remote_serve.add_argument("--token", default="")
    p_remote_serve.set_defaults(func=cmd_remote_serve)

    p_dash = sub.add_parser("dash", aliases=["d"], help="终端仪表盘")
    p_dash.add_argument("--limit", type=int, default=5)
    p_dash.set_defaults(func=cmd_dash)

    p_status = sub.add_parser("status", aliases=["st"], help="查看工作流总览")
    p_status.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = load_config()
    conn = connect_db()
    init_db(conn)
    try:
        return int(args.func(args, cfg, conn))
    except ModelError as exc:
        print(f"[模型错误] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"[执行失败] {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
