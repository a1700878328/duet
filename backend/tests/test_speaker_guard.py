"""发言人归属守卫单测（纯逻辑，无 live 调用）。"""

from app.speaker_guard import find_impersonations, sanitize

FORBIDDEN = ["艾琳", "卡尔"]


def test_blocks_impersonation_of_human_character():
    text = "[旁白]: 地牢阴森。\n\n[卡尔]: （压低声音）我有办法。"
    clean, violated = sanitize(text, FORBIDDEN)
    assert violated is True
    assert "卡尔" not in clean.replace("旁白", "")  # 卡尔 的发言段被剥掉
    assert "地牢阴森" in clean  # 旁白保留


def test_keeps_npc_and_narrator():
    text = "[旁白]: 风穿过回廊。\n\n[莉莉丝]: 我的小骑士，别紧张。"
    clean, violated = sanitize(text, FORBIDDEN)
    assert violated is False
    assert "莉莉丝" in clean
    assert "风穿过回廊" in clean


def test_narration_about_human_char_is_ok():
    # 旁白里描写卡尔（叙述），不是冒充卡尔开口 —— 应保留
    text = "[旁白]: 卡尔握紧了短斧，盯着裂缝。"
    clean, violated = sanitize(text, FORBIDDEN)
    assert violated is False
    assert "卡尔握紧" in clean


def test_unlabeled_text_preserved():
    clean, violated = sanitize("触手在阴影里蠕动。", FORBIDDEN)
    assert violated is False
    assert "触手" in clean


def test_full_chinese_colon_and_spacing():
    text = "[卡尔]：我来了"
    assert find_impersonations(text, FORBIDDEN) == ["卡尔"]
    clean, violated = sanitize(text, FORBIDDEN)
    assert violated is True
    assert clean == ""  # 全是冒充 → 被清空（上层会回退旁白）
