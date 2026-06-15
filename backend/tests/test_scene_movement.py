from app.scene_movement import (
    clean_scene_name,
    infer_npc_moves_from_text,
    parse_scene_simulation_output,
)


def test_clean_scene_name_keeps_specific_named_place() -> None:
    assert clean_scene_name("南边境集市的“破靴子”酒馆方向") == "破靴子酒馆"


def test_infer_npc_move_from_offscreen_prose() -> None:
    text = (
        "露西娅站在洞口外，等她的雇主消失在石隙里，便吐了口唾沫，"
        "转身朝南边境集市的“破靴子”酒馆方向走去。"
    )

    moves = infer_npc_moves_from_text(text, ["露西娅"], source_scene="南部边境")

    assert moves == [{"npc": "露西娅", "scene": "破靴子酒馆"}]


def test_parse_scene_simulation_json_moves() -> None:
    text, moves = parse_scene_simulation_output(
        '{"text":"露西娅离开洞口。","moves":[{"npc":"露西娅","scene":"破靴子酒馆"}]}',
        ["露西娅"],
        source_scene="南部边境",
    )

    assert text == "露西娅离开洞口。"
    assert moves == [{"npc": "露西娅", "scene": "破靴子酒馆"}]
