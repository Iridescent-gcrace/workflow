from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any


class ModelError(RuntimeError):
    pass


def _http_post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise ModelError(f"模型请求失败: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelError(f"模型响应不是合法 JSON: {raw[:300]}") from exc


def _resolve_route(
    cfg: dict[str, Any],
    profile: str,
    provider_override: str | None,
    model_override: str | None,
) -> tuple[str, str, dict[str, Any], str]:
    profiles = cfg.get("profiles", {})
    profile_cfg = profiles.get(profile)
    if profile_cfg is None:
        raise ModelError(f"未找到 profile: {profile}")

    provider = provider_override or profile_cfg.get("provider")
    model = model_override or profile_cfg.get("model")
    if not provider or not model:
        raise ModelError(f"profile 配置不完整: {profile}")

    provider_cfg = cfg.get("providers", {}).get(provider)
    if provider_cfg is None:
        raise ModelError(f"未找到 provider 配置: {provider}")

    api_key_env = provider_cfg.get("api_key_env")
    if not api_key_env:
        raise ModelError(f"provider `{provider}` 缺少 api_key_env 配置")
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise ModelError(f"缺少环境变量 `{api_key_env}`，无法调用模型")
    return provider, model, provider_cfg, api_key


def _ask_openai(model: str, provider_cfg: dict[str, Any], api_key: str, prompt: str) -> str:
    base_url = str(provider_cfg.get("base_url", "https://api.openai.com/v1")).rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = _http_post_json(url, headers, payload)
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelError(f"OpenAI 返回结构异常: {json.dumps(data)[:300]}") from exc
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
    return str(content).strip()


def _ask_gemini(model: str, provider_cfg: dict[str, Any], api_key: str, prompt: str) -> str:
    base_url = str(provider_cfg.get("base_url", "https://generativelanguage.googleapis.com/v1beta")).rstrip("/")
    quoted_model = urllib.parse.quote(model, safe="")
    quoted_key = urllib.parse.quote(api_key, safe="")
    url = f"{base_url}/models/{quoted_model}:generateContent?key={quoted_key}"
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    headers = {"Content-Type": "application/json"}
    data = _http_post_json(url, headers, payload)
    candidates = data.get("candidates", [])
    if not candidates:
        raise ModelError(f"Gemini 返回为空: {json.dumps(data)[:300]}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()
    if not text:
        raise ModelError(f"Gemini 文本为空: {json.dumps(data)[:300]}")
    return text


def ask_model(
    cfg: dict[str, Any],
    prompt: str,
    profile: str = "fast",
    provider_override: str | None = None,
    model_override: str | None = None,
) -> str:
    provider, model, provider_cfg, api_key = _resolve_route(cfg, profile, provider_override, model_override)
    if provider == "openai":
        return _ask_openai(model, provider_cfg, api_key, prompt)
    if provider == "gemini":
        return _ask_gemini(model, provider_cfg, api_key, prompt)
    raise ModelError(f"暂不支持 provider: {provider}")

