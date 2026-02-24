from __future__ import annotations

import re
from pathlib import Path


def normalize_tags(raw: str | None) -> str:
    if not raw:
        return ""
    parts: list[str] = []
    for token in raw.split(","):
        normalized = token.strip().lower()
        if normalized and normalized not in parts:
            parts.append(normalized)
    return ",".join(parts)


def auto_title(text: str, max_len: int = 40) -> str:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "").strip()
    if not line:
        return "untitled-capture"
    if len(line) <= max_len:
        return line
    return line[: max_len - 1] + "…"


def slugify(text: str, max_len: int = 50) -> str:
    s = text.lower().strip()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-_]", "", s)
    s = s.strip("-_")
    if not s:
        s = "note"
    return s[:max_len]


def read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")

