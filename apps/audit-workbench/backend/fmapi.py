"""Foundation Model API calls as the caller (OBO model-serving scope)."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from .auth import CallerIdentity
from .config import get_settings


def chat(caller: CallerIdentity, messages: list[dict[str, Any]], tools: list[dict] | None = None,
         max_tokens: int = 4000) -> dict[str, Any]:
    """One chat-completions call. Returns the first choice's message (content and/or tool_calls)."""
    if caller.is_anonymous:
        raise HTTPException(401, "Model calls need an OBO token.")
    s = get_settings()
    # No temperature: current Claude endpoints reject it.
    body: dict[str, Any] = {"messages": messages, "max_tokens": max_tokens}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    resp = httpx.post(f"{s.workspace_url}/serving-endpoints/{s.serving_endpoint_name}/invocations",
                      headers={"Authorization": f"Bearer {caller.access_token}"}, json=body, timeout=120)
    if resp.status_code >= 400:
        raise HTTPException(502, f"Model endpoint error {resp.status_code}: {resp.text[:300]}")
    return resp.json()["choices"][0]["message"]


def call_model(caller: CallerIdentity, prompt: str, max_tokens: int = 2000, system: str | None = None) -> str:
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    content = chat(caller, msgs, max_tokens=max_tokens).get("content")
    if isinstance(content, list):  # some endpoints return content parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""
