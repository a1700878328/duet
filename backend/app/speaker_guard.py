"""发言人归属守卫（fail-closed）。

AI 只能以 NPC 或「旁白」开口，绝不能以真人玩家的角色名说话。
仿 rp_system 的 char_resolve：与其指望提示词自觉，不如在输出层强制拦截。

粒度：只拦「以真人角色名作为说话者」的段落（`[卡尔]: …`），
不影响旁白里**描写**该角色（`[旁白]: 卡尔握紧了剑`）—— 那是叙述，不是冒充。
"""

import re

# 形如 [名字]:  或  [名字]：  的说话人标签
_LABEL_RE = re.compile(r"\[([^\]\n]{1,24})\]\s*[:：]\s*")


def _norm(s: str) -> str:
    return s.strip().lower().replace(" ", "").replace("　", "")


def _segments(text: str) -> list[tuple[str | None, str]]:
    """按说话人标签把文本切成 (label|None, body) 段，保序。无标签整段 label=None。"""
    matches = list(_LABEL_RE.finditer(text))
    if not matches:
        stripped = text.strip()
        return [(None, stripped)] if stripped else []
    out: list[tuple[str | None, str]] = []
    if matches[0].start() > 0:
        pre = text[: matches[0].start()].strip()
        if pre:
            out.append((None, pre))
    for i, m in enumerate(matches):
        label = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        out.append((label, body))
    return out


def find_impersonations(text: str, forbidden: list[str]) -> list[str]:
    """返回文本中以真人角色名开口的说话人标签列表（用于检测/评测）。"""
    forb = {_norm(f) for f in forbidden if f}
    hits: list[str] = []
    for label, _ in _segments(text):
        if label is not None and _norm(label) in forb:
            hits.append(label)
    return hits


def sanitize(text: str, forbidden: list[str]) -> tuple[str, bool]:
    """剥掉所有「以真人角色名开口」的段落。返回 (clean_text, violated)。"""
    forb = {_norm(f) for f in forbidden if f}
    kept: list[str] = []
    violated = False
    for label, body in _segments(text):
        if label is not None and _norm(label) in forb:
            violated = True
            continue
        if not body:
            continue
        kept.append(body if label is None else f"[{label}]: {body}")
    return "\n\n".join(kept).strip(), violated
