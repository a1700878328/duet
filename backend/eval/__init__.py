"""Duet RP-quality EVAL harness (design doc §7).

Runs scenario probes through the REAL brain (DeepSeek) + the speaker guard,
exactly as the app does (same prompt path), scores 7 quality dimensions, and
writes a JSONL ledger + summary.

LIVE (real API). Gated: only runs when ``DUET_EVAL_LIVE=1`` (or ``--live``).
Never hits the API under pytest.

Run the full suite (Windows: set ``PYTHONUTF8=1``)::

    cd backend
    DUET_EVAL_LIVE=1 uv run python -m eval.run

Offline self-test (no API) — proves the deterministic scorer logic::

    uv run python -m eval.run --selftest
"""
