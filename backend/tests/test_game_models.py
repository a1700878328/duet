from app.game_models import parse_stats, sheet_to_flat


def test_parse_stats_promotes_legacy_items_and_statuses() -> None:
    sheet = parse_stats(
        {
            "职业": "女骑士",
            "金钱": 80,
            "物品": ["药草", "药草", "生锈短剑"],
            "状态": ["监禁:哥布林 5", "负债"],
        }
    )

    assert sheet.职业 == "女骑士"
    assert sheet.金钱 == 80
    assert [(i.name, i.quantity) for i in sheet.物品栏] == [
        ("药草", 2),
        ("生锈短剑", 1),
    ]
    assert [(s.id, s.group, s.days) for s in sheet.状态] == [
        ("监禁:哥布林", "监禁", 5),
        ("负债", "债务", 0),
    ]


def test_sheet_to_flat_keeps_legacy_storage_shape() -> None:
    sheet = parse_stats({"物品": ["药草"], "状态": ["监禁:哥布林 2"]})

    flat = sheet_to_flat(sheet)

    assert flat["物品"] == ["药草"]
    assert flat["状态"] == ["监禁:哥布林 2"]
