"""Guard: importing app.memory must NOT construct mem0 (no network/model load).

The store is a lazy singleton; merely importing it and referencing MemoryStore
must stay cheap and side-effect-free. We make NO live calls here.
"""

from __future__ import annotations

import app.memory as memory
from app.memory import MemoryStore, store


def test_import_does_not_build_client() -> None:
    # Class is referenceable and the module-level singleton exists.
    assert isinstance(store, MemoryStore)
    # No mem0 client was constructed at import time.
    assert MemoryStore._client is None
    assert MemoryStore._failed is False


def test_search_empty_query_is_noop_without_building() -> None:
    # Empty query short-circuits before any client construction.
    assert store.search("room_test", "   ") == ""
    assert MemoryStore._client is None
    assert MemoryStore._failed is False


def test_module_exposes_expected_api() -> None:
    assert hasattr(memory, "MemoryStore")
    assert callable(store.remember)
    assert callable(store.search)
