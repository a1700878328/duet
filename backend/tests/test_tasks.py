from app.stats import apply_delta, default_stats
from app.tasks import extract_task_directives, normalize_task_offer


def test_extract_task_offer_marker_is_hidden_from_visible_text() -> None:
    clean, offers, completions = extract_task_directives(
        '会长把羊皮纸推过来。[[委托:{"标题":"清剿洞窟","奖励":{"金钱":30,"经验":20}}]]'
    )

    assert clean == "会长把羊皮纸推过来。"
    assert offers[0]["标题"] == "清剿洞窟"
    assert completions == []


def test_normalize_task_offer_rewards() -> None:
    task = normalize_task_offer(
        {
            "标题": "清剿洞窟",
            "目标": ["进入洞窟", "带回证据"],
            "奖励": {"金钱": 30, "经验": 20, "物品": ["生锈短剑"], "好感度": 2},
        },
        issuer="公会会长",
        issuer_npc_id=1,
        time_label="冒险第1周·第1天·上午",
    )

    assert task["title"] == "清剿洞窟"
    assert task["issuer"] == "公会会长"
    assert task["issuer_npc_id"] == 1
    assert task["status"] == "可接取"
    assert task["objectives"] == ["进入洞窟", "带回证据"]
    assert task["rewards"]["金钱"] == 30
    assert task["rewards"]["经验"] == 20
    assert task["rewards"]["物品"] == ["生锈短剑"]
    assert task["rewards"]["好感度"] == {"公会会长": 2}


def test_item_reward_enters_inventory() -> None:
    stats = default_stats()

    updated = apply_delta(stats, {"物品_add": ["生锈短剑"], "经验": 20})

    assert updated["物品"] == ["生锈短剑"]
    assert updated["经验"] == 20
