"""Extract Chinese narrative strings from obfuscated ksim JS bundles.

The game ships as hash-named, javascript-obfuscator output. Narrative text
survives as single-quoted string literals containing CJK. We regex those out,
decode JS escapes, and group by module (filename stem before the first dot).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from pydantic import BaseModel

# CJK Unified Ideographs (incl. extension blocks covered by the BMP range below).
_CJK = re.compile(r"[一-鿿]")
# Single-quoted JS string literal with escape awareness: '...' allowing \' and \\.
_JS_STR = re.compile(r"'((?:[^'\\]|\\.)*)'")
# stat-key -> 中文 label map in main*.js, e.g.  str':'力量'
_STAT_PAIR = re.compile(r"([a-z_]{2,15})':'([一-鿿]{1,10})'")
# class names declared in the class_list, e.g.  name':'战士'
_CLASS_NAME = re.compile(r"name':'([一-鿿]{2,6})'")

# Modules that are engine/UI only — no narrative prose.
_SKIP_MODULES = frozenset({"btn", "events", "init"})
# The engine bundle — parsed separately for the glossary, never as narrative.
_ENGINE_MODULE = "main"

GLOSSARY_MODULE = "_glossary"

# stat tokens that, alone or with +数字/标点, are pure UI noise (not prose).
_STAT_TOKENS = frozenset(
    {"经验", "状态", "金币", "金钱", "点数", "等级", "力量", "敏捷", "智力", "意志"}
)
_NOISE = re.compile(
    r"^[\s+\-0-9.,，。、:：()（）%]*"
    r"(?:" + "|".join(_STAT_TOKENS) + r")?"
    r"[\s+\-0-9.,，。、:：()（）%]*$"
)


class ExtractResult(BaseModel):
    """Narrative strings grouped by module, plus the engine glossary blob."""

    modules: dict[str, list[str]]
    glossary: str

    @property
    def total_strings(self) -> int:
        return sum(len(v) for v in self.modules.values())


def _decode_js(raw: str) -> str:
    r"""Decode JS string escapes: \n \t \r \uXXXX \' \\ and friends."""

    def repl(m: re.Match[str]) -> str:
        esc = m.group(1)
        match esc[0]:
            case "u":
                return chr(int(esc[1:], 16))
            case "x":
                return chr(int(esc[1:], 16))
            case "n":
                return "\n"
            case "t":
                return "\t"
            case "r":
                return "\r"
            case _:
                return esc  # \' -> ' , \\ -> \ , etc.

    return re.sub(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", repl, raw)


def _module_of(path: Path) -> str:
    """`goblin.0299122d.js` -> `goblin`."""
    return path.name.split(".", 1)[0]


def _is_narrative(s: str) -> bool:
    """Keep dialogue/prose; drop short fragments and pure stat/UI noise."""
    if len(s) < 4:
        return False
    if not _CJK.search(s):
        return False
    return not _NOISE.match(s)


def _extract_strings(text: str) -> list[str]:
    out: list[str] = []
    for m in _JS_STR.finditer(text):
        decoded = _decode_js(m.group(1))
        if _CJK.search(decoded):
            out.append(decoded)
    return out


def _build_glossary(text: str) -> str:
    """Turn main*.js stat map + class names into a readable Chinese blob."""
    seen: dict[str, str] = {}
    for key, label in _STAT_PAIR.findall(text):
        seen.setdefault(key, label)
    classes = sorted(set(_CLASS_NAME.findall(text)))

    lines = ["《女骑士模拟器》术语表"]
    if seen:
        lines.append("属性与状态：")
        lines += [f"- {label}（{key}）" for key, label in seen.items()]
    if classes:
        lines.append("可选职业：" + "、".join(classes))
    return "\n".join(lines)


def extract(src_dir: Path) -> ExtractResult:
    """Read every `*.js` under `src_dir`; return narrative + glossary."""
    modules: dict[str, list[str]] = {}
    glossary = ""

    for path in sorted(src_dir.glob("*.js")):
        module = _module_of(path)
        text = path.read_text(encoding="utf-8", errors="replace")

        if module == _ENGINE_MODULE:
            glossary = _build_glossary(text)
            continue
        if module in _SKIP_MODULES:
            continue

        strings = [s for s in _extract_strings(text) if _is_narrative(s)]
        if strings:
            modules.setdefault(module, []).extend(strings)

    return ExtractResult(modules=modules, glossary=glossary)


def _default_src() -> Path:
    return Path(r"C:\Users\a1700\Desktop\ksim-local")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else _default_src()
    result = extract(src)
    for module in sorted(result.modules):
        print(f"{module:14s} {len(result.modules[module]):5d}")
    print(f"{'TOTAL':14s} {result.total_strings:5d}")
    print(f"glossary chars: {len(result.glossary)}")


if __name__ == "__main__":
    main()
