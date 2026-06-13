"""Read-only lore retrieval for grounding roleplay in 《女骑士模拟器》.

The vector store is built offline by `lore.ingest`. This module opens the
persisted chromadb collection lazily and embeds queries with the same fastembed
Chinese model. Everything here is SYNC — call it from async code via
`asyncio.to_thread`. If the store is missing (never ingested), search degrades
to empty results and the app keeps running.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
_COLLECTION = "ksim"
# backend/app/lore.py -> backend/lore/chroma
_CHROMA_DIR = Path(__file__).resolve().parent.parent / "lore" / "chroma"

_embedder: Any | None = None
_collection: Any | None = None
_load_failed = False


def _get_embedder() -> Any:
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding

        _embedder = TextEmbedding(model_name=_EMBED_MODEL)
    return _embedder


def _get_collection() -> Any | None:
    """Open the persisted collection once; cache None on any failure."""
    global _collection, _load_failed
    if _collection is not None:
        return _collection
    if _load_failed:
        return None
    try:
        import chromadb

        if not _CHROMA_DIR.exists():
            raise FileNotFoundError(f"lore store not found at {_CHROMA_DIR}")
        client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        _collection = client.get_collection(_COLLECTION)
        return _collection
    except Exception as exc:
        _load_failed = True
        logger.warning("lore store unavailable (run `python -m lore.ingest`): %s", exc)
        return None


class LoreStore:
    """Singleton facade over the ksim vector store. Cheap to call repeatedly."""

    def search(
        self, query: str, k: int = 4, world: str = "ksim"
    ) -> list[dict[str, Any]]:
        """Return up to `k` relevant passages: [{text, module, score}].

        `world` is accepted for forward-compat; only "ksim" is wired today.
        Cosine distance is converted to a 0..1 similarity score.
        """
        if world != "ksim" or not query.strip():
            return []
        collection = _get_collection()
        if collection is None:
            return []
        try:
            embedding = next(iter(_get_embedder().embed([query]))).tolist()
            res = collection.query(
                query_embeddings=[embedding],
                n_results=k,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.warning("lore search failed: %s", exc)
            return []

        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        out: list[dict[str, Any]] = []
        for doc, meta, dist in zip(docs, metas, dists, strict=False):
            out.append(
                {
                    "text": doc,
                    "module": (meta or {}).get("module", "?"),
                    "score": round(1.0 - float(dist), 4),
                }
            )
        return out

    def search_formatted(self, query: str, k: int = 4) -> str:
        """Compact Chinese block for prompt injection; "" if no hits."""
        hits = self.search(query, k=k)
        if not hits:
            return ""
        lines = ["【世界设定·相关片段】"]
        for h in hits:
            snippet = " ".join(h["text"].split())
            lines.append(f"- ({h['module']}) {snippet}")
        return "\n".join(lines)


store = LoreStore()
