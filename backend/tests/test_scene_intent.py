from app.ws import _infer_scene_destination, _is_departure_confirmation

KNOWN_SCENES = [
    "冒险者公会",
    "城镇",
    "酒馆",
    "借贷商店",
    "旅店",
    "森林",
    "洞窟",
    "青楼街",
]


def test_infers_explicit_travel_to_border() -> None:
    assert _infer_scene_destination("我们去南部边境打哥布林吧", KNOWN_SCENES) == ""


def test_infers_goblin_target_as_border() -> None:
    assert _infer_scene_destination("去打哥布林", KNOWN_SCENES) == ""


def test_confirmation_is_not_a_direct_destination() -> None:
    assert _is_departure_confirmation("好，走吧")
    assert _infer_scene_destination("好，走吧", KNOWN_SCENES) == ""


def test_greeting_does_not_move_scene() -> None:
    assert _infer_scene_destination("会长，你好", KNOWN_SCENES) == ""


def test_asking_for_goblin_info_does_not_move_scene() -> None:
    assert _infer_scene_destination("我想打听哥布林的消息", KNOWN_SCENES) == ""


def test_role_style_destination_then_departure_moves() -> None:
    text = "艾琳娜转身走向门口，铁靴踏地声干脆利落。“南部边境。走。”"
    assert _infer_scene_destination(text, KNOWN_SCENES) == ""
