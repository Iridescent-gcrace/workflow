from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from aiwf.config import NOTES_DIR, ensure_app_dirs
from aiwf.utils import slugify


def read_clipboard() -> str:
    candidates = [
        ["pbpaste"],
        ["wl-paste"],
        ["xclip", "-o", "-selection", "clipboard"],
    ]
    for cmd in candidates:
        try:
            proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
        text = proc.stdout.strip()
        if text:
            return text
    raise RuntimeError("无法读取剪贴板，请检查 pbpaste/wl-paste/xclip 是否可用，或使用 --content/--file。")


def write_note_markdown(title: str, raw_content: str, note: str) -> Path:
    ensure_app_dirs()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = NOTES_DIR / f"{ts}-{slugify(title)}.md"
    body = (
        f"# {title}\n\n"
        f"## AI 笔记\n\n"
        f"{note.strip()}\n\n"
        f"## 原始内容\n\n"
        f"{raw_content.strip()}\n"
    )
    path.write_text(body, encoding="utf-8")
    return path

