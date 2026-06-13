"""Ksim lore RAG pipeline — extract → ingest → query 《女骑士模拟器》 narrative.

Build the store offline with `python -m lore.ingest`; the app reads it via
`app.lore.LoreStore`. chromadb/fastembed are sync libs by design.
"""
