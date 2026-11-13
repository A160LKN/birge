"""Колонки, карточки, порядок, конфликт правок, комментарии."""
import pytest

from app.services import cards as cards_service

pytestmark = pytest.mark.api


def titles(user, board_id: int, column_id: int) -> list[str]:
    board = user.get(f"/boards/{board_id}").json()
    return [c["title"] for c in board["cards"] if c["column_id"] == column_id]


def column_titles(user, board_id: int) -> list[str]:
    return [c["title"] for c in user.get(f"/boards/{board_id}").json()["columns"]]


# ---------- Колонки ----------

def test_add_rename_and_delete_column(alice, team):
    created = alice.post(f"/boards/{team['id']}/columns", json={"title": "Тестирование"})
    assert created.status_code == 201
    column = created.json()
    assert column_titles(alice, team["id"])[-1] == "Тестирование"
    assert alice.patch(f"/columns/{column['id']}", json={"title": "QA"}).json()["title"] == "QA"
    assert alice.delete(f"/columns/{column['id']}").status_code == 204
    assert "QA" not in column_titles(alice, team["id"])


def test_move_column(alice, team):
    todo, doing, done = (c["id"] for c in team["columns"])
    alice.post(f"/columns/{done}/move", json={"after_id": None})
    assert column_titles(alice, team["id"]) == ["Готово", "Нужно сделать", "В работе"]
    alice.post(f"/columns/{done}/move", json={"after_id": doing})
    assert column_titles(alice, team["id"]) == ["Нужно сделать", "В работе", "Готово"]
    assert alice.post(f"/columns/{done}/move", json={"after_id": done}).status_code == 422


def test_column_limit(alice, monkeypatch):
    monkeypatch.setattr(cards_service, "MAX_COLUMNS", 4)
    board = alice.board()
    assert alice.post(f"/boards/{board['id']}/columns", json={"title": "4"}).status_code == 201
    response = alice.post(f"/boards/{board['id']}/columns", json={"title": "5"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "columns_limit"


def test_last_column_cannot_be_deleted(alice, team):
    first, second, third = (c["id"] for c in team["columns"])
    alice.delete(f"/columns/{first}")
    alice.delete(f"/columns/{second}")
    response = alice.delete(f"/columns/{third}")
    assert response.status_code == 409 and response.json()["error"]["code"] == "last_column"


def test_deleting_column_deletes_its_cards(alice, team):
    column = team["columns"][0]["id"]
    card = alice.card(column)
    alice.delete(f"/columns/{column}")
    assert alice.get(f"/cards/{card['id']}").status_code == 404


def test_stranger_cannot_touch_columns(alice, team, make_user):
    stranger = make_user()
    column = team["columns"][0]["id"]
    assert stranger.patch(f"/columns/{column}", json={"title": "x"}).status_code == 404
    assert stranger.delete(f"/columns/{column}").status_code == 404
    assert stranger.post(f"/boards/{team['id']}/columns", json={"title": "x"}).status_code == 404


# ---------- Карточки ----------

def test_new_cards_go_to_the_bottom(alice, team):
    column = team["columns"][0]["id"]
    for name in ("Первая", "Вторая", "Третья"):
        alice.card(column, name)
    assert titles(alice, team["id"], column) == ["Первая", "Вторая", "Третья"]


def test_card_fields_and_detail(alice, bob, team):
    card = alice.card(team["columns"][0]["id"], "  Сверстать лендинг  ", description="Макет в Figma")
    assert card["title"] == "Сверстать лендинг" and card["version"] == 1
    updated = bob.patch(f"/cards/{card['id']}", json={
        "version": 1, "description": "Макет утверждён", "assignee_id": bob.id, "due_date": "2026-12-01"})
    assert updated.status_code == 200
    body = updated.json()
    assert (body["description"], body["assignee_id"], body["due_date"], body["version"]) == (
        "Макет утверждён", bob.id, "2026-12-01", 2)
    detail = alice.get(f"/cards/{card['id']}").json()
    assert detail["created_by"] == alice.id and detail["comment_list"] == [] and detail["attachment_list"] == []


def test_clearing_assignee_and_due_date(alice, team):
    card = alice.card(team["columns"][0]["id"])
    card = alice.patch(f"/cards/{card['id']}", json={"version": 1, "assignee_id": alice.id,
                                                     "due_date": "2026-12-01"}).json()
    cleared = alice.patch(f"/cards/{card['id']}", json={"version": card["version"], "assignee_id": None,
                                                        "due_date": None}).json()
    assert cleared["assignee_id"] is None and cleared["due_date"] is None


def test_concurrent_edit_is_a_conflict_not_a_silent_overwrite(alice, bob, team):
    """Оба открыли карточку версии 1. Бауыржан сохранил первым — правка Алии не должна молча
    затереть его текст: она получает 409 и актуальную версию, чтобы решить, что делать."""
    card = alice.card(team["columns"][0]["id"], "Договор")
    assert bob.patch(f"/cards/{card['id']}", json={"version": 1, "description": "Текст Бауыржана"}).status_code == 200
    conflict = alice.patch(f"/cards/{card['id']}", json={"version": 1, "description": "Текст Алии"})
    assert conflict.status_code == 409
    error = conflict.json()["error"]
    assert error["code"] == "version_conflict"
    assert error["details"]["current"]["description"] == "Текст Бауыржана"
    assert error["details"]["current"]["version"] == 2
    retry = alice.patch(f"/cards/{card['id']}", json={"version": 2, "description": "Текст Алии"})
    assert retry.status_code == 200 and retry.json()["version"] == 3


def test_moving_does_not_conflict_with_editing(alice, bob, team):
    """Пока Алия правит описание, Бауыржан перетащил карточку — это не конфликт."""
    card = alice.card(team["columns"][0]["id"])
    bob.post(f"/cards/{card['id']}/move", json={"column_id": team["columns"][1]["id"], "after_id": None})
    assert alice.patch(f"/cards/{card['id']}", json={"version": 1, "description": "Новое"}).status_code == 200


@pytest.mark.parametrize(("patch", "code"), [
    ({"version": 1}, "nothing_to_update"),
])
def test_empty_patch(alice, team, patch, code):
    card = alice.card(team["columns"][0]["id"])
    response = alice.patch(f"/cards/{card['id']}", json=patch)
    assert response.status_code == 422 and response.json()["error"]["code"] == code


@pytest.mark.parametrize("patch", [
    {"title": "Без версии"},
    {"version": 1, "title": None},
    {"version": 1, "title": "   "},
    {"version": 1, "description": None},
    {"version": 1, "title": "x" * 201},
    {"version": 0, "title": "x"},
    {"version": 1, "due_date": "завтра"},
    {"version": 1, "priority": "high"},
])
def test_invalid_patch_is_rejected(alice, team, patch):
    card = alice.card(team["columns"][0]["id"])
    assert alice.patch(f"/cards/{card['id']}", json=patch).status_code == 422


def test_assignee_must_be_a_member(alice, team, make_user):
    card = alice.card(team["columns"][0]["id"])
    stranger = make_user()
    response = alice.patch(f"/cards/{card['id']}", json={"version": 1, "assignee_id": stranger.id})
    assert response.status_code == 422 and response.json()["error"]["code"] == "not_a_member"


def test_move_within_and_between_columns(alice, team):
    todo, doing, _ = (c["id"] for c in team["columns"])
    a, b, c = (alice.card(todo, name) for name in "ABC")

    alice.post(f"/cards/{c['id']}/move", json={"column_id": todo, "after_id": None})   # наверх
    assert titles(alice, team["id"], todo) == ["C", "A", "B"]
    alice.post(f"/cards/{c['id']}/move", json={"column_id": todo, "after_id": a["id"]})  # между A и B
    assert titles(alice, team["id"], todo) == ["A", "C", "B"]
    alice.post(f"/cards/{a['id']}/move", json={"column_id": todo, "after_id": b["id"]})  # в самый низ
    assert titles(alice, team["id"], todo) == ["C", "B", "A"]

    moved = alice.post(f"/cards/{b['id']}/move", json={"column_id": doing, "after_id": None})
    assert moved.status_code == 200 and moved.json()["column_id"] == doing
    assert titles(alice, team["id"], todo) == ["C", "A"] and titles(alice, team["id"], doing) == ["B"]


def test_many_moves_keep_a_consistent_order(alice, team):
    """Двадцать перестановок подряд в одну и ту же щель — ключи растут, порядок верный."""
    column = team["columns"][0]["id"]
    first = alice.card(column, "Первая")
    alice.card(column, "Последняя")
    for n in range(20):
        card = alice.card(column, f"№{n}")
        alice.post(f"/cards/{card['id']}/move", json={"column_id": column, "after_id": first["id"]})
    order = titles(alice, team["id"], column)
    assert order[0] == "Первая" and order[-1] == "Последняя"
    assert order[1:-1] == [f"№{n}" for n in reversed(range(20))]


@pytest.mark.parametrize("case", ["after_itself", "after_card_in_other_column", "unknown_after"])
def test_invalid_moves(alice, team, case):
    todo, doing, _ = (c["id"] for c in team["columns"])
    card = alice.card(todo)
    other = alice.card(doing)
    after = {"after_itself": card["id"], "after_card_in_other_column": other["id"], "unknown_after": 999}[case]
    response = alice.post(f"/cards/{card['id']}/move", json={"column_id": todo, "after_id": after})
    assert response.status_code == 422


def test_cannot_move_card_to_another_board(alice, team):
    other_board = alice.board("Другая")
    card = alice.card(team["columns"][0]["id"])
    response = alice.post(f"/cards/{card['id']}/move",
                          json={"column_id": other_board["columns"][0]["id"], "after_id": None})
    assert response.status_code == 404


def test_stranger_cannot_read_or_change_cards(alice, team, make_user):
    card = alice.card(team["columns"][0]["id"])
    stranger = make_user()
    assert stranger.get(f"/cards/{card['id']}").status_code == 404
    assert stranger.patch(f"/cards/{card['id']}", json={"version": 1, "title": "x"}).status_code == 404
    assert stranger.post(f"/cards/{card['id']}/move", json={"column_id": team["columns"][0]["id"]}).status_code == 404
    assert stranger.delete(f"/cards/{card['id']}").status_code == 404
    assert stranger.post("/cards", json={"column_id": team["columns"][0]["id"], "title": "x"}).status_code == 404
    assert stranger.post(f"/cards/{card['id']}/comments", json={"body": "x"}).status_code == 404


def test_card_limit(alice, monkeypatch):
    monkeypatch.setattr(cards_service, "MAX_CARDS_PER_BOARD", 2)
    board = alice.board()
    column = board["columns"][0]["id"]
    alice.card(column)
    alice.card(column)
    response = alice.post("/cards", json={"column_id": column, "title": "Третья"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "cards_limit"


def test_delete_card(alice, team):
    card = alice.card(team["columns"][0]["id"])
    assert alice.delete(f"/cards/{card['id']}").status_code == 204
    assert alice.get(f"/cards/{card['id']}").status_code == 404
    assert alice.delete(f"/cards/{card['id']}").status_code == 404


# ---------- Комментарии ----------

def test_comments_are_listed_in_order_with_author(alice, bob, team):
    card = alice.card(team["columns"][0]["id"])
    alice.post(f"/cards/{card['id']}/comments", json={"body": "Когда готово?"})
    reply = bob.post(f"/cards/{card['id']}/comments", json={"body": "  Завтра  "})
    assert reply.status_code == 201 and reply.json()["body"] == "Завтра"
    detail = alice.get(f"/cards/{card['id']}").json()
    assert [(c["author"]["name"], c["body"]) for c in detail["comment_list"]] == [
        ("Алия", "Когда готово?"), ("Бауыржан", "Завтра")]
    assert detail["comments"] == 2


@pytest.mark.parametrize("body", ["", "   ", "x" * 2001])
def test_invalid_comment(alice, team, body):
    card = alice.card(team["columns"][0]["id"])
    assert alice.post(f"/cards/{card['id']}/comments", json={"body": body}).status_code == 422
