"""Chunk + embed ksim narrative into a local chromadb collection.

Run `python -m lore.ingest` to (re)build the store. Idempotent: the "ksim"
collection is dropped and recreated each run. Embeddings come from fastembed's
`BAAI/bge-small-zh-v1.5` (Chinese ONNX model) — passed explicitly so Chroma's
default English MiniLM is never used.
"""

from __future__ import annotations

import sys
from pathlib import Path

import chromadb
from fastembed import TextEmbedding
from pydantic import BaseModel

from .extract import GLOSSARY_MODULE, ExtractResult, extract

EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
COLLECTION = "ksim"
CHROMA_DIR = Path(__file__).parent / "chroma"
_TARGET_CHARS = 220
_MAX_CHARS = 320


class Chunk(BaseModel):
    module: str
    chunk_index: int
    text: str

    @property
    def doc_id(self) -> str:
        return f"{self.module}:{self.chunk_index}"


def _pack(module: str, strings: list[str]) -> list[Chunk]:
    """Greedy-join ordered strings into ~400-char passages, never mid-string."""
    chunks: list[Chunk] = []
    buf: list[str] = []
    size = 0
    idx = 0

    def flush() -> None:
        nonlocal buf, size, idx
        if buf:
            chunks.append(Chunk(module=module, chunk_index=idx, text="\n".join(buf)))
            idx += 1
            buf, size = [], 0

    for s in strings:
        add = len(s) + (1 if buf else 0)
        if buf and size + add > _MAX_CHARS:
            flush()
            add = len(s)
        buf.append(s)
        size += add
        if size >= _TARGET_CHARS:
            flush()
    flush()
    return chunks


def build_chunks(result: ExtractResult) -> list[Chunk]:
    chunks: list[Chunk] = []
    for module in sorted(result.modules):
        chunks.extend(_pack(module, result.modules[module]))
    if result.glossary:
        chunks.extend(_pack(GLOSSARY_MODULE, [result.glossary]))
    return chunks


def ingest(src_dir: Path, *, chroma_dir: Path = CHROMA_DIR) -> int:
    """Extract, chunk, embed, and persist. Returns the final doc count."""
    result = extract(src_dir)
    chunks = build_chunks(result)
    if not chunks:
        raise RuntimeError("no narrative chunks produced — check the source dir")

    embedder = TextEmbedding(model_name=EMBED_MODEL)
    embeddings = [v.tolist() for v in embedder.embed(c.text for c in chunks)]

    chroma_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_dir))
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass  # first run / not present
    collection = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})

    collection.add(
        ids=[c.doc_id for c in chunks],
        documents=[c.text for c in chunks],
        embeddings=embeddings,
        metadatas=[{"module": c.module, "chunk_index": c.chunk_index} for c in chunks],
    )
    return collection.count()


def _default_src() -> Path:
    return Path(r"C:\Users\a1700\Desktop\ksim-local")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else _default_src()
    count = ingest(src)
    print(f"ingested {count} chunks into collection '{COLLECTION}' at {CHROMA_DIR}")


if __name__ == "__main__":
    main()
