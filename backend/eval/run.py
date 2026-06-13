"""Async eval runner + offline self-test + summary.

Usage (Windows: set PYTHONUTF8=1)::

    cd backend
    DUET_EVAL_LIVE=1 uv run python -m eval.run            # full live suite
    DUET_EVAL_LIVE=1 uv run python -m eval.run -k context # one scenario, live
    uv run python -m eval.run --selftest                  # offline, no API

LIVE is gated: without DUET_EVAL_LIVE=1 (or --live) the runner refuses to call
the API, so a stray `pytest` import can never burn tokens.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.brain import BrainProvider, default_provider
from app.speaker_guard import sanitize

from .scenarios import SCENARIOS, Scenario
from .scorers import (
    OOC_MARKERS,
    REFUSAL_MARKERS,
    contains,
    delivered_impersonates,
    found_markers,
    has_english_cot,
    llm_judge,
)

LEDGER_DIR = Path(__file__).resolve().parent / "ledger"

# Per-dimension pass-rate threshold. Below this => suite fails (nonzero exit).
THRESHOLDS: dict[str, float] = {
    "consistency": 1.0,
    "hallucination": 1.0,
    "attribution": 1.0,  # fail-closed: delivered output must NEVER impersonate
    "context": 1.0,
    "card_loaded": 1.0,
    "identity": 1.0,
    "ooc": 1.0,
}


@dataclass(slots=True)
class Result:
    scenario_id: str
    dimension: str
    passed: bool
    score: float
    detail: str
    raw_violated: bool  # model TRIED to impersonate pre-guard (key metric)
    delivered_clean: bool  # delivered output impersonates nobody
    raw_excerpt: str = ""
    delivered_excerpt: str = ""


# ---------------------------------------------------------------------------
# Guarded generation — mirrors app.ws._generate_guarded (complete -> sanitize).
# ---------------------------------------------------------------------------
async def guarded_generate(
    brain: BrainProvider, scenario: Scenario
) -> tuple[str, str, bool]:
    """Return (raw, delivered, raw_violated) using the same path as the app."""
    messages = scenario.build_messages()
    forbidden = scenario.forbidden()
    raw = (await brain.complete(messages)).strip()
    delivered, violated = sanitize(raw, forbidden)
    if violated or not delivered:
        # One corrective regeneration, exactly like app.ws does.
        names = "、".join(forbidden) or "（无）"
        corrective = messages + [
            {
                "role": "system",
                "content": (
                    "纠正：你刚才以真人玩家的角色名开口了，这是被禁止的。"
                    "请重写：只能扮演 NPC 或「旁白」，每段以 [NPC名]: 或 [旁白]: 开头，"
                    f"绝不能以这些真人角色名作为说话者：{names}。"
                ),
            }
        ]
        raw2 = (await brain.complete(corrective)).strip()
        delivered2, _ = sanitize(raw2, forbidden)
        if delivered2:
            delivered = delivered2
    return raw, delivered, violated


# ---------------------------------------------------------------------------
# Per-dimension scoring.
# ---------------------------------------------------------------------------
async def score(
    brain: BrainProvider, scenario: Scenario, raw: str, delivered: str
) -> tuple[bool, str]:
    """Apply the dimension's scorer. Returns (passed, detail)."""
    exp = scenario.expect
    forbidden = scenario.forbidden()

    # Deterministic gates first (cheap, no API).
    if exp.get("no_impersonation"):
        hits = delivered_impersonates(delivered, forbidden)
        if hits:
            return False, f"delivered impersonates human-player chars: {hits}"
        return True, "delivered impersonates nobody (guard held)"

    if isinstance(exp.get("must_contain"), str):
        needle = exp["must_contain"]
        if not contains(delivered, needle):
            # For card_loaded, fall back to the LLM judge if a token check misses.
            if exp.get("criteria"):
                jr = await llm_judge(
                    brain,
                    criteria=str(exp["criteria"]),
                    answer=delivered,
                    question=scenario.probe,
                )
                return jr.passed, f"substring miss; judge: {jr.reason}"
            return False, f"missing required substring {needle!r}"
        return True, f"contains required fact {needle!r}"

    if exp.get("no_ooc_markers"):
        ooc = found_markers(delivered, OOC_MARKERS)
        if ooc:
            return False, f"OOC/system-tone markers present: {ooc}"
        if has_english_cot(delivered):
            return False, "leaked English chain-of-thought"
        return True, "no OOC markers, no leaked reasoning"

    if exp.get("no_refusal"):
        refusals = found_markers(delivered, REFUSAL_MARKERS)
        if refusals or len(delivered.strip()) < 20:
            return False, f"refusal/empty (markers={refusals}, len={len(delivered)})"
        return True, "in-character, no refusal"

    # LLM-judged dimensions.
    if exp.get("criteria"):
        jr = await llm_judge(
            brain,
            criteria=str(exp["criteria"]),
            answer=delivered,
            question=scenario.probe,
        )
        return jr.passed, jr.reason

    return False, "no scorer matched scenario.expect"


async def run_scenario(brain: BrainProvider, scenario: Scenario) -> Result:
    raw, delivered, raw_violated = await guarded_generate(brain, scenario)
    delivered_clean = delivered_impersonates(delivered, scenario.forbidden()) == []
    passed, detail = await score(brain, scenario, raw, delivered)
    return Result(
        scenario_id=scenario.id,
        dimension=scenario.dimension,
        passed=passed,
        score=1.0 if passed else 0.0,
        detail=detail,
        raw_violated=raw_violated,
        delivered_clean=delivered_clean,
        raw_excerpt=raw[:200],
        delivered_excerpt=delivered[:200],
    )


# ---------------------------------------------------------------------------
# Ledger + summary.
# ---------------------------------------------------------------------------
def write_ledger(run_id: str, results: list[Result]) -> Path:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    path = LEDGER_DIR / f"eval-{run_id}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    return path


def _bar(rate: float, width: int = 14) -> str:
    fill = round(rate * width)
    return "█" * fill + "·" * (width - fill)


def print_summary(results: list[Result]) -> bool:
    """Print a per-dimension table. Returns True if all thresholds met."""
    by_dim: dict[str, list[Result]] = {}
    for r in results:
        by_dim.setdefault(r.dimension, []).append(r)

    print()
    print("=" * 72)
    print("  Duet RP EVAL — per-dimension summary")
    print("=" * 72)
    header = (
        f"  {'dimension':<14}{'pass/total':>12}{'rate':>8}  "
        f"{'thr':>5}  {'':<16}  ok"
    )
    print(header)
    print("  " + "-" * 68)

    all_ok = True
    for dim in sorted(by_dim):
        rs = by_dim[dim]
        passed = sum(1 for r in rs if r.passed)
        total = len(rs)
        rate = passed / total if total else 0.0
        thr = THRESHOLDS.get(dim, 1.0)
        ok = rate >= thr
        all_ok = all_ok and ok
        print(
            f"  {dim:<14}{f'{passed}/{total}':>12}{rate:>7.0%}  "
            f"{thr:>5.0%}  {_bar(rate):<16}  {'PASS' if ok else 'FAIL'}"
        )

    raw_tries = sum(1 for r in results if r.raw_violated)
    delivered_dirty = sum(1 for r in results if not r.delivered_clean)
    overall_pass = sum(1 for r in results if r.passed)
    print("  " + "-" * 68)
    print(
        f"  OVERALL       {f'{overall_pass}/{len(results)}':>12}"
        f"{overall_pass / len(results):>7.0%}"
    )
    print()
    print(
        f"  fail-closed proof: raw impersonation attempts = {raw_tries}/"
        f"{len(results)};  delivered still dirty = {delivered_dirty}/"
        f"{len(results)} (must be 0)"
    )
    print("=" * 72)
    return all_ok and delivered_dirty == 0


# ---------------------------------------------------------------------------
# Offline self-test — proves deterministic scorer logic without the API.
# ---------------------------------------------------------------------------
def selftest() -> int:
    print("running offline self-test (no API) ...")
    checks: list[tuple[str, bool]] = []

    forbidden = ["艾琳", "卡尔"]
    impersonating = "[旁白]: 火光摇曳。\n\n[卡尔]: 我看看左边。"
    clean = "[旁白]: 火光摇曳。\n\n[守卫格罗姆]: 站住！"

    # sanitize strips the impersonating segment; find_impersonations confirms.
    delivered, violated = sanitize(impersonating, forbidden)
    imp_raw = delivered_impersonates(impersonating, forbidden)
    imp_clean = delivered_impersonates(delivered, forbidden)
    checks.append(("sanitize flags impersonation", violated is True))
    checks.append(("delivered clean after sanitize", imp_clean == []))
    checks.append(("raw impersonation detected", imp_raw == ["卡尔"]))
    checks.append(
        ("clean text: no impersonation", delivered_impersonates(clean, forbidden) == [])
    )

    # OOC markers.
    checks.append(
        ("OOC marker present", found_markers("作为AI，我必须说……", OOC_MARKERS) != [])
    )
    checks.append(
        ("OOC marker absent", found_markers("[旁白]: 夜幕降临了。", OOC_MARKERS) == [])
    )
    checks.append(
        ("english CoT leak detected", has_english_cot("Let me think first.") is True)
    )
    checks.append(
        ("no english CoT in clean RP", has_english_cot("[旁白]: 篝火噼啪。") is False)
    )

    # Refusal markers.
    nsfw = "[莉莉丝]: 她俯身贴近，气息拂过对方的脖颈……"
    checks.append(
        ("refusal detected", found_markers("抱歉，我无法继续。", REFUSAL_MARKERS) != [])
    )
    checks.append(
        ("no refusal in NSFW content", found_markers(nsfw, REFUSAL_MARKERS) == [])
    )

    # Substring (context / card-loaded).
    checks.append(("substring present", contains("暗号月光鸢尾", "月光鸢尾") is True))
    checks.append(("substring absent", contains("暗号忘了", "月光鸢尾") is False))

    # Scenarios build messages via the real prompt path without error.
    for s in SCENARIOS:
        msgs = s.build_messages()
        ok = bool(msgs) and msgs[0]["role"] == "system" and msgs[-1]["role"] == "user"
        checks.append((f"scenario builds messages: {s.id}", ok))

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  [{'ok' if ok else 'XX'}] {name}")
    print()
    if failed:
        print(f"SELFTEST FAILED: {len(failed)} check(s): {failed}")
        return 1
    print(f"SELFTEST PASSED: {len(checks)}/{len(checks)} deterministic checks ok")
    return 0


# ---------------------------------------------------------------------------
# Entrypoint.
# ---------------------------------------------------------------------------
async def run_live(scenarios: list[Scenario]) -> int:
    brain = default_provider()
    if not brain.api_key:
        print("FAIL: no DEEPSEEK_API_KEY configured (.env). Cannot run live.")
        return 2
    run_id = str(int(time.time()))
    print(f"LIVE eval · run_id={run_id} · {len(scenarios)} scenario(s)")
    results: list[Result] = []
    for s in scenarios:
        print(f"  -> {s.dimension:<14} {s.id} ...", flush=True)
        try:
            r = await run_scenario(brain, s)
        except Exception as exc:  # noqa: BLE001 — record, keep going
            r = Result(
                scenario_id=s.id,
                dimension=s.dimension,
                passed=False,
                score=0.0,
                detail=f"runtime error: {exc!r}",
                raw_violated=False,
                delivered_clean=True,
            )
        results.append(r)
        print(f"     {'PASS' if r.passed else 'FAIL'} — {r.detail[:80]}")

    path = write_ledger(run_id, results)
    all_ok = print_summary(results)
    print(f"\nledger: {path}")
    return 0 if all_ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Duet RP EVAL harness")
    ap.add_argument(
        "--selftest", action="store_true", help="offline deterministic check (no API)"
    )
    ap.add_argument(
        "--live", action="store_true", help="force live run (= DUET_EVAL_LIVE=1)"
    )
    ap.add_argument(
        "-k", dest="select", default="", help="filter on scenario id/dimension"
    )
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    live = args.live or os.environ.get("DUET_EVAL_LIVE") == "1"
    if not live:
        print(
            "refusing to run LIVE (real API) without opt-in.\n"
            "  set DUET_EVAL_LIVE=1 (or pass --live) for the live suite, or\n"
            "  use --selftest for the offline deterministic check."
        )
        return 3

    scenarios = SCENARIOS
    if args.select:
        sel = args.select.lower()
        scenarios = [
            s for s in SCENARIOS if sel in s.id.lower() or sel in s.dimension.lower()
        ]
        if not scenarios:
            print(f"no scenario matches -k {args.select!r}")
            return 4

    return asyncio.run(run_live(scenarios))


if __name__ == "__main__":
    sys.exit(main())
