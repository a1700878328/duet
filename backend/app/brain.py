"""DeepSeek (OpenAI-compatible) streaming adapter.

deepseek-v4-flash is a thinking model: each SSE delta may carry
`delta.reasoning_content` (chain-of-thought) and/or `delta.content`.
We yield ONLY `delta.content` and drop reasoning entirely.

Provider is fully parametrised (base_url / model / key / extra body) so the
Qwen fallback (http://192.168.1.102:8080/v1, enable_thinking=false) is a
one-line switch.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import settings


@dataclass(slots=True)
class BrainProvider:
    api_key: str
    base_url: str
    model: str
    agent_name: str = "default"
    # Extra body kwargs merged into every request (e.g. chat_template_kwargs).
    extra_body: dict[str, Any] = field(default_factory=dict)
    temperature: float = 0.9
    max_tokens: int = 600
    timeout: float = 120.0

    def _body(self, messages: list[dict[str, str]], *, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": stream,
            # Best-effort: ask the model to skip thinking. Unknown params are
            # tolerated server-side; content-only filtering keeps us correct.
            "chat_template_kwargs": {"thinking": False},
        }
        # Merge caller-supplied extras (e.g. Qwen's enable_thinking=false),
        # allowing nested chat_template_kwargs to be overridden/extended.
        for key, value in self.extra_body.items():
            if (
                key == "chat_template_kwargs"
                and isinstance(value, dict)
                and isinstance(body.get(key), dict)
            ):
                body[key] = {**body[key], **value}
            else:
                body[key] = value
        return body

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """Yield content chunks (reasoning_content ignored)."""
        body = self._body(messages, stream=True)
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout
        ) as client:
            async with client.stream(
                "POST",
                "/chat/completions",
                headers=self._headers,
                json=body,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    chunk = _parse_sse_content(line)
                    if chunk:
                        yield chunk

    async def complete(self, messages: list[dict[str, str]]) -> str:
        """Non-streaming helper. Returns full content (reasoning dropped)."""
        body = self._body(messages, stream=False)
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout
        ) as client:
            resp = await client.post(
                "/chat/completions", headers=self._headers, json=body
            )
            resp.raise_for_status()
            data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        return (choice.get("message") or {}).get("content") or ""


def _parse_sse_content(line: str) -> str | None:
    """Extract delta.content from one SSE line. None for keep-alive/done/other."""
    line = line.strip()
    if not line or not line.startswith("data:"):
        return None
    payload = line[len("data:") :].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    choice = (data.get("choices") or [{}])[0]
    delta = choice.get("delta") or {}
    # Yield ONLY content; reasoning_content is chain-of-thought — ignore it.
    content = delta.get("content")
    return content or None


@dataclass(frozen=True, slots=True)
class AgentProfile:
    """Per-agent runtime knobs. Model stays shared unless settings changes it."""

    temperature: float
    max_tokens: int
    timeout: float = 120.0
    extra_body: dict[str, Any] = field(default_factory=dict)


AGENT_PROFILES: dict[str, AgentProfile] = {
    "default": AgentProfile(temperature=0.9, max_tokens=800),
    # Stable JSON planners/judges.
    "director": AgentProfile(temperature=0.25, max_tokens=900),
    "npc_impulse": AgentProfile(temperature=0.2, max_tokens=320),
    "stats_judge": AgentProfile(temperature=0.15, max_tokens=500),
    "npc_move_consent": AgentProfile(temperature=0.2, max_tokens=500),
    # Expressive writing.
    "npc_dialogue": AgentProfile(temperature=0.9, max_tokens=800),
    "ending": AgentProfile(temperature=0.75, max_tokens=800),
    # Design / prompt work.
    "character_design": AgentProfile(temperature=0.65, max_tokens=1200),
    "npc_design": AgentProfile(temperature=0.65, max_tokens=1000),
    "image_prompt": AgentProfile(temperature=0.5, max_tokens=1000),
    "image_prompt_translate": AgentProfile(temperature=0.35, max_tokens=600),
    "scene_prompt": AgentProfile(temperature=0.35, max_tokens=800),
    # Background maintenance.
    "npc_enrich": AgentProfile(temperature=0.25, max_tokens=700),
    "card_rewrite": AgentProfile(temperature=0.5, max_tokens=800),
}


def agent_provider(agent_name: str) -> BrainProvider:
    """Return a fresh DeepSeek provider instance for one logical AI role.

    All roles use the same configured model (currently deepseek-v4-flash) so cost
    stays predictable; the separation is for temperature/token isolation and
    clearer call-site intent.
    """
    profile = AGENT_PROFILES.get(agent_name, AGENT_PROFILES["default"])
    return BrainProvider(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        agent_name=agent_name,
        max_tokens=profile.max_tokens,
        temperature=profile.temperature,
        timeout=profile.timeout,
        extra_body=dict(profile.extra_body),
    )


def default_provider() -> BrainProvider:
    return agent_provider("default")
