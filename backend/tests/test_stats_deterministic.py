from app.stats import (
    apply_delta,
    default_stats,
    infer_deterministic_delta,
    infer_payment_total,
    initial_stats_from_card,
)


def test_default_stats_no_longer_tracks_spending_field() -> None:
    assert "支出" not in default_stats()


def test_initial_stats_follow_selected_character_card() -> None:
    stats = initial_stats_from_card("艾琳娜·铁壁", "沉默的女骑士，重甲盾卫")

    assert stats["职业"] == "女骑士"
    assert stats["力量"] == 12
    assert stats["意志"] == 13
    assert stats["金钱"] == 120


def test_paying_one_silver_coin_reduces_money() -> None:
    stats = default_stats()
    scene = "艾琳娜: （从钱袋中抽出一枚银币，稳稳落在露西娅面前的沙地上）带路。"

    delta = infer_deterministic_delta(scene, stats)
    updated = apply_delta(stats, delta)

    assert delta == {"金钱": -1}
    assert updated["金钱"] == 99


def test_asking_for_money_does_not_reduce_money() -> None:
    stats = default_stats()
    scene = "露西娅: 带路啊？行啊，不过我的时间不是白给的。一个银币。"

    assert infer_deterministic_delta(scene, stats) == {}


def test_tip_with_amount_after_comma_is_detected() -> None:
    assert infer_payment_total("我再送你个小费，100银币") == 100


def test_overpaying_creates_debt_if_text_says_it_happened() -> None:
    stats = default_stats()
    stats["金钱"] = 99

    delta = infer_deterministic_delta("艾琳娜: 我再送你个小费，100银币。", stats)
    updated = apply_delta(stats, delta)

    assert delta == {"金钱": -100, "状态_add": ["负债"]}
    assert updated["金钱"] == -1
    assert "负债" in updated["状态"]
