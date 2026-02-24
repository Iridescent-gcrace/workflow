from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_DIR = Path(os.getenv("AIWF_HOME", Path.home() / ".aiwf"))
CONFIG_PATH = APP_DIR / "config.json"
DB_PATH = APP_DIR / "aiwf.db"
LOG_DIR = APP_DIR / "logs"
NOTES_DIR = APP_DIR / "notes"

DEFAULT_CONFIG: dict[str, Any] = {
    "profiles": {
        "fast": {"provider": "openai", "model": "gpt-4.1-mini"},
        "deep": {"provider": "gemini", "model": "gemini-2.5-pro"},
        "balanced": {"provider": "openai", "model": "gpt-4.1"},
    },
    "providers": {
        "openai": {
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
        },
        "gemini": {
            "api_key_env": "GEMINI_API_KEY",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
        },
    },
}


def ensure_app_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    ensure_app_dirs()
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict[str, Any]) -> None:
    ensure_app_dirs()
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")

