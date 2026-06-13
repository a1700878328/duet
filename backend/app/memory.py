"""Long-term episodic memory for duet (SP-4): mem0 OSS.

DeepSeek (non-thinking `deepseek-chat`) extracts durable RP facts; fastembed
(BAAI/bge-small-zh-v1.5, 512-dim) embeds them; a local on-disk qdrant store
persists them under `app/memory_store/`.

Everything here is SYNC — call it from async code via `asyncio.to_thread`.
Mirrors `lore.py`'s lazy-singleton + graceful-degrade contract: nothing heavy
(mem0 / qdrant / embedder / network) is touched at import time. The client is
built on first use; if construction fails we log a warning and degrade to a
no-op so the app keeps running.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import settings

logger = logging.getLogger(__name__)

_DEEPSEEK_MODEL = "deepseek-chat"  # non-thinking: faster/cheaper for extraction
_EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
_EMBED_DIMS = 512
_COLLECTION = "duet_memory"

# backend/app/memory.py -> backend/app/memory_store/
_STORE_DIR = Path(__file__).resolve().parent / "memory_store"
_QDRANT_DIR = _STORE_DIR / "qdrant"
_HISTORY_DB = _STORE_DIR / "history.db"

_CUSTOM_INSTRUCTIONS = (
    "你在为一个双人协作的成人向角色扮演（NSFW RP）会话维护长期记忆。"
    "只提取可长期复用的事实：角色身份与设定、人物关系、世界/剧情中反复出现的"
    "稳定事实（如重要物品的名字与来历、地点、誓言、长期目标、立场）、玩家偏好与"
    "长期约定。忽略一次性的旁白、寒暄问候、临时动作或情绪描写、语气词，以及"
    "纯粹的情色细节。事实要写得明确、可独立理解。"
)


class MemoryStore:
    """Lazy singleton facade over a mem0 OSS store. Cheap to call repeatedly.

    Degrades to a no-op (search -> "", remember -> nothing) if mem0 cannot be
    constructed (missing key, import error, qdrant failure, …).
    """

    _client: Any | None = None
    _failed: bool = False

    def _get_client(self) -> Any | None:
        """Build the mem0 client once; cache None on any failure."""
        if MemoryStore._client is not None:
            return MemoryStore._client
        if MemoryStore._failed:
            return None
        if not settings.deepseek_api_key:
            MemoryStore._failed = True
            logger.warning("memory disabled: missing deepseek_api_key")
            return None
        try:
            from mem0 import Memory

            _QDRANT_DIR.mkdir(parents=True, exist_ok=True)
            config = {
                "llm": {
                    "provider": "deepseek",
                    "config": {
                        "model": _DEEPSEEK_MODEL,
                        "api_key": settings.deepseek_api_key,
                        "deepseek_base_url": (
                            settings.deepseek_base_url or "https://api.deepseek.com"
                        ),
                        "temperature": 0.1,
                    },
                },
                "embedder": {
                    "provider": "fastembed",
                    "config": {
                        "model": _EMBED_MODEL,
                        "embedding_dims": _EMBED_DIMS,
                    },
                },
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "collection_name": _COLLECTION,
                        "embedding_model_dims": _EMBED_DIMS,
                        "path": str(_QDRANT_DIR),
                        "on_disk": True,
                    },
                },
                "history_db_path": str(_HISTORY_DB),
                "custom_instructions": _CUSTOM_INSTRUCTIONS,
            }
            MemoryStore._client = Memory.from_config(config)
            logger.info("memory enabled: deepseek + fastembed + local qdrant")
            return MemoryStore._client
        except Exception as exc:
            MemoryStore._failed = True
            logger.warning("memory store unavailable, degrading to no-op: %s", exc)
            return None

    def remember(self, scope: str, user_text: str, ai_text: str) -> None:
        """Extract & persist durable facts from one RP exchange. Best-effort."""
        client = self._get_client()
        if client is None:
            return
        messages = [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": ai_text},
        ]
        try:
            client.add(messages=messages, user_id=scope, infer=True)
        except Exception as exc:
            logger.warning("memory remember failed (scope=%s): %s", scope, exc)

    def search(self, scope: str, query: str, k: int = 4) -> str:
        """Compact Chinese block of relevant memories; "" if none/unavailable."""
        if not query.strip():
            return ""
        client = self._get_client()
        if client is None:
            return ""
        try:
            # mem0 2.0.x: scope goes in filters (not top-level), and the count
            # kwarg is `top_k` (not `limit`).
            res = client.search(query, filters={"user_id": scope}, top_k=k)
        except Exception as exc:
            logger.warning("memory search failed (scope=%s): %s", scope, exc)
            return ""

        items = res.get("results", []) if isinstance(res, dict) else (res or [])
        lines: list[str] = []
        seen: set[str] = set()
        for item in items:
            memory = str((item or {}).get("memory") or "").strip()
            if memory and memory not in seen:
                seen.add(memory)
                lines.append(f"- {memory}")
        if not lines:
            return ""
        return "【相关记忆】\n" + "\n".join(lines)


store = MemoryStore()
