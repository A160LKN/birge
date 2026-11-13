"""WebSocket: авторизация, события в реальном времени, присутствие, догонялка после обрыва, отключение."""
import pytest
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.realtime import hub as hub_module
from tests.conftest import Closed, connect, nothing_more, receive, receive_type

pytestmark = pytest.mark.api


def test_events_arrive_live_to_other_members(alice, bob, team):
    column = team["columns"][0]["id"]
    with connect(bob, team["id"]) as ws:
        card = alice.card(column, "Новая")
        event = receive_type(ws, "card.created")
        assert event["data"]["title"] == "Новая" and event["actor_id"] == alice.id
        assert event["data"]["activity"]["message"] == "Новая карточка «Новая» в колонке «Нужно сделать»"

        alice.patch(f"/cards/{card['id']}", json={"version": 1, "title": "Переименована"})
        assert receive_type(ws, "card.updated")["data"]["title"] == "Переименована"

        alice.post(f"/cards/{card['id']}/move", json={"column_id": team["columns"][2]["id"]})
        assert receive_type(ws, "card.moved")["data"]["column_id"] == team["columns"][2]["id"]

        alice.post(f"/cards/{card['id']}/comments", json={"body": "Готово!"})
        assert receive_type(ws, "comment.created")["data"]["body"] == "Готово!"

        alice.delete(f"/cards/{card['id']}")
        assert receive_type(ws, "card.deleted")["data"]["id"] == card["id"]


def test_client_id_lets_the_author_recognise_own_changes(alice, team):
    with connect(alice, team["id"]) as ws:
        alice.post("/cards", json={"column_id": team["columns"][0]["id"], "title": "Моя"},
                   headers={"X-Client-Id": "tab-1"})
        assert receive_type(ws, "card.created")["client_id"] == "tab-1"


def test_invalid_client_id_header_is_rejected(alice, team):
    response = alice.post("/cards", json={"column_id": team["columns"][0]["id"], "title": "x"},
                          headers={"X-Client-Id": "<script>"})
    assert response.status_code == 422


def test_failed_change_sends_nothing(alice, bob, team):
    card = alice.card(team["columns"][0]["id"])
    alice.patch(f"/cards/{card['id']}", json={"version": 1, "title": "v2"})
    with connect(bob, team["id"], last_event_id=10**6) as ws:
        assert bob.patch(f"/cards/{card['id']}", json={"version": 1, "title": "старая"}).status_code == 409
        assert nothing_more(ws)  # конфликт откатил транзакцию — события нет


def test_other_boards_events_are_not_delivered(alice, bob, team):
    other = alice.board("Личная")
    last = bob.get(f"/boards/{team['id']}").json()["last_event_id"]
    with connect(bob, team["id"], last_event_id=last) as ws:
        alice.card(other["columns"][0]["id"])
        assert nothing_more(ws)


def test_presence_shows_who_is_on_the_board(alice, bob, team):
    with connect(alice, team["id"]) as alice_ws:
        assert alice_ws.ready["presence"] == [alice.id]
        with connect(bob, team["id"]) as bob_ws:
            assert sorted(bob_ws.ready["presence"]) == sorted([alice.id, bob.id])
            assert receive_type(alice_ws, "presence")["users"] == sorted([alice.id, bob.id])
            with connect(bob, team["id"]):  # вторая вкладка того же человека — присутствие не меняется
                assert nothing_more(alice_ws)
            assert nothing_more(alice_ws)
        assert receive_type(alice_ws, "presence")["users"] == [alice.id]


def test_missed_events_are_resent_after_reconnect(alice, bob, team):
    """Связь пропала — по last_event_id клиент получает всё, что случилось без него, и в том же порядке."""
    column = team["columns"][0]["id"]
    snapshot = bob.get(f"/boards/{team['id']}").json()
    alice.card(column, "Пока Бауыржан был офлайн — 1")
    alice.card(column, "Пока Бауыржан был офлайн — 2")
    with connect(bob, team["id"], last_event_id=snapshot["last_event_id"]) as ws:
        first = receive_type(ws, "card.created")
        second = receive_type(ws, "card.created")
        assert [first["data"]["title"], second["data"]["title"]] == [
            "Пока Бауыржан был офлайн — 1", "Пока Бауыржан был офлайн — 2"]
        assert first["id"] < second["id"]
        assert nothing_more(ws)


def test_too_many_missed_events_ask_for_full_reload(alice, bob, team, monkeypatch):
    monkeypatch.setattr(hub_module, "RESUME_LIMIT", 2)
    column = team["columns"][0]["id"]
    for n in range(3):
        alice.card(column, str(n))
    with connect(bob, team["id"], last_event_id=0) as ws:
        assert receive_type(ws, "resync") == {"type": "resync"}


def test_ping_pong_and_unknown_messages(bob, team):
    with connect(bob, team["id"]) as ws:
        ws.send_json({"type": "ping"})
        assert receive_type(ws, "pong") == {"type": "pong"}
        ws.send_text("не json")
        assert receive_type(ws, "error")["code"] == "bad_message"


def test_removed_member_is_disconnected(alice, bob, team):
    with connect(bob, team["id"]) as ws:
        alice.delete(f"/boards/{team['id']}/members/{bob.id}")
        assert receive_type(ws, "member.removed")["data"]["user_id"] == bob.id
        with pytest.raises(Closed) as closed:
            receive(ws)
        assert closed.value.code == 4403  # больше не участник — живые обновления прекращаются сразу


def test_everyone_is_disconnected_when_board_is_deleted(alice, bob, team):
    with connect(bob, team["id"]) as ws:
        alice.delete(f"/boards/{team['id']}")
        receive_type(ws, "board.deleted")
        with pytest.raises(Closed) as closed:
            receive(ws)
        assert closed.value.code == 4404


# ---------- Авторизация сокета ----------

def _first_reply(client, board_id: int, message):
    with client.websocket_connect(f"/ws/boards/{board_id}") as ws:
        if isinstance(message, str):
            ws.send_text(message)
        elif message is not None:
            ws.send_json(message)
        reply = receive(ws)
        with pytest.raises((Closed, WebSocketDisconnect)) as closed:
            receive(ws)
        code = closed.value.code
        return reply, code


@pytest.mark.parametrize(("message", "code", "error"), [
    ("привет", 4400, "bad_message"),
    ({"type": "hello"}, 4400, "bad_message"),
    ({"type": "auth"}, 4400, "bad_message"),
    ({"type": "auth", "token": "garbage"}, 4401, "invalid_token"),
])
def test_bad_auth_messages(client, team, message, code, error):
    reply, closed = _first_reply(client, team["id"], message)
    assert reply["type"] == "error" and reply["code"] == error and closed == code


def test_auth_timeout(client, team, monkeypatch):
    monkeypatch.setattr(settings, "ws_auth_timeout_seconds", 0.2)
    reply, closed = _first_reply(client, team["id"], None)
    assert reply["code"] == "auth_timeout" and closed == 4401


def test_stranger_cannot_subscribe(client, team, make_user):
    stranger = make_user()
    reply, closed = _first_reply(client, team["id"], {"type": "auth", "token": stranger.token})
    assert reply["code"] == "not_found" and closed == 4404


def test_token_is_not_accepted_in_url(client, alice, team):
    """Токен в адресе попал бы в логи — сервер его там даже не ищет."""
    with client.websocket_connect(f"/ws/boards/{team['id']}?token={alice.token}") as ws:
        ws.send_json({"type": "ping"})
        assert receive(ws)["code"] == "bad_message"
