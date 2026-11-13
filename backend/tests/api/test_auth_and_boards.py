"""Вход, доски, участники и права доступа."""
import pytest

from tests.conftest import PASSWORD

pytestmark = pytest.mark.api


# ---------- Вход ----------

def test_register_returns_token_and_user(client):
    response = client.post("/auth/register", json={"email": " Aigerim@Test.KZ ", "name": " Айгерим ",
                                                   "password": PASSWORD})
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "aigerim@test.kz" and body["user"]["name"] == "Айгерим"
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["email"] == "aigerim@test.kz"


def test_email_is_unique_regardless_of_case(client, alice):
    response = client.post("/auth/register", json={"email": alice.email.upper(), "name": "Двойник",
                                                   "password": PASSWORD})
    assert response.status_code == 409 and response.json()["error"]["code"] == "email_taken"


@pytest.mark.parametrize("body", [
    {"email": "not-an-email", "name": "А", "password": PASSWORD},
    {"email": "a@test.kz", "name": "   ", "password": PASSWORD},
    {"email": "a@test.kz", "name": "А", "password": "short"},
    {"email": "a@test.kz", "name": "А" * 61, "password": PASSWORD},
    {"email": "a@test.kz", "name": "А", "password": PASSWORD, "role": "admin"},  # лишнее поле
])
def test_invalid_registration(client, body):
    assert client.post("/auth/register", json=body).status_code == 422


def test_login(client, alice):
    response = client.post("/auth/login", json={"email": alice.email, "password": PASSWORD})
    assert response.status_code == 200 and response.json()["user"]["id"] == alice.id


def test_wrong_password_and_unknown_email_look_the_same(client, alice):
    wrong = client.post("/auth/login", json={"email": alice.email, "password": "wrong-password"})
    unknown = client.post("/auth/login", json={"email": "nobody@test.kz", "password": "wrong-password"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()  # нельзя узнать, кто зарегистрирован


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer garbage"}, {"Authorization": "Basic abc"}])
def test_protected_endpoints_need_valid_token(client, headers):
    assert client.get("/boards", headers=headers).status_code == 401


# ---------- Доски ----------

def test_new_board_has_three_columns_and_owner(alice):
    board = alice.board("Запуск сайта")
    assert board["title"] == "Запуск сайта" and board["role"] == "owner"
    assert [c["title"] for c in board["columns"]] == ["Нужно сделать", "В работе", "Готово"]
    assert [m["user"]["id"] for m in board["members"]] == [alice.id]
    assert board["cards"] == [] and board["last_event_id"] == 0


def test_board_list_shows_role_and_counts(alice, bob, team):
    alice.card(team["columns"][0]["id"])
    own = bob.board("Личная")
    boards = bob.get("/boards").json()
    assert [(b["id"], b["role"], b["members"]) for b in boards] == [(own["id"], "owner", 1),
                                                                  (team["id"], "member", 2)]
    assert boards[1]["cards"] == 1


def test_stranger_cannot_see_board_and_gets_404(alice, make_user):
    board = alice.board()
    stranger = make_user("Чужой")
    for response in (stranger.get(f"/boards/{board['id']}"),
                     stranger.patch(f"/boards/{board['id']}", json={"title": "Взлом"}),
                     stranger.delete(f"/boards/{board['id']}"),
                     stranger.get(f"/boards/{board['id']}/activity")):
        assert response.status_code == 404  # 404, а не 403: не раскрываем, что доска существует


def test_only_owner_renames_and_deletes(alice, bob, team):
    assert bob.patch(f"/boards/{team['id']}", json={"title": "Моё"}).status_code == 403
    assert bob.delete(f"/boards/{team['id']}").status_code == 403
    renamed = alice.patch(f"/boards/{team['id']}", json={"title": "Релиз 2.0"})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Релиз 2.0"
    assert alice.delete(f"/boards/{team['id']}").status_code == 204
    assert bob.get(f"/boards/{team['id']}").status_code == 404


def test_deleting_board_removes_everything(alice, team, run_jobs):
    card = alice.card(team["columns"][0]["id"])
    alice.post(f"/cards/{card['id']}/comments", json={"body": "Комментарий"})
    alice.delete(f"/boards/{team['id']}")
    assert alice.get(f"/cards/{card['id']}").status_code == 404


@pytest.mark.parametrize("board_id", [0, -1, 2_147_483_648, "abc"])
def test_out_of_range_ids_are_validated(alice, board_id):
    assert alice.get(f"/boards/{board_id}").status_code == 422  # а не 500 от базы


# ---------- Участники ----------

def test_owner_adds_member_by_email(alice, bob):
    board = alice.board()
    response = alice.post(f"/boards/{board['id']}/members", json={"email": bob.email.upper()})
    assert response.status_code == 201
    assert response.json() == {"user": {"id": bob.id, "email": bob.email, "name": bob.name}, "role": "member"}
    assert bob.get(f"/boards/{board['id']}").status_code == 200


@pytest.mark.parametrize(("email", "status", "code"), [
    ("nobody@test.kz", 404, "user_not_found"),
])
def test_cannot_add_unknown_user(alice, email, status, code):
    board = alice.board()
    response = alice.post(f"/boards/{board['id']}/members", json={"email": email})
    assert response.status_code == status and response.json()["error"]["code"] == code


def test_cannot_add_member_twice(alice, bob, team):
    response = alice.post(f"/boards/{team['id']}/members", json={"email": bob.email})
    assert response.status_code == 409 and response.json()["error"]["code"] == "already_member"


def test_member_cannot_invite(alice, bob, team, make_user):
    carol = make_user("Карина")
    assert bob.post(f"/boards/{team['id']}/members", json={"email": carol.email}).status_code == 403


def test_removed_member_loses_access_and_their_cards_are_unassigned(alice, bob, team):
    card = alice.card(team["columns"][0]["id"])
    alice.patch(f"/cards/{card['id']}", json={"version": card["version"], "assignee_id": bob.id})
    assert alice.delete(f"/boards/{team['id']}/members/{bob.id}").status_code == 204
    assert bob.get(f"/boards/{team['id']}").status_code == 404
    after = alice.get(f"/cards/{card['id']}").json()
    assert after["assignee_id"] is None and after["version"] == card["version"] + 2


def test_member_can_leave_but_owner_cannot(alice, bob, team):
    owner_leaves = alice.delete(f"/boards/{team['id']}/members/{alice.id}")
    assert owner_leaves.status_code == 409 and owner_leaves.json()["error"]["code"] == "owner_cannot_leave"
    assert bob.delete(f"/boards/{team['id']}/members/{bob.id}").status_code == 204


def test_member_cannot_remove_others(alice, bob, team, make_user):
    carol = make_user("Карина")
    alice.post(f"/boards/{team['id']}/members", json={"email": carol.email})
    assert bob.delete(f"/boards/{team['id']}/members/{carol.id}").status_code == 403


def test_removing_non_member(alice, team, make_user):
    stranger = make_user()
    assert alice.delete(f"/boards/{team['id']}/members/{stranger.id}").status_code == 404


def test_activity_feed_with_pagination(alice, bob, team):
    column = team["columns"][0]["id"]
    for n in range(3):
        alice.card(column, f"Задача {n}")
    feed = bob.get(f"/boards/{team['id']}/activity", params={"limit": 2}).json()
    assert [a["message"] for a in feed] == ["Новая карточка «Задача 2» в колонке «Нужно сделать»",
                                            "Новая карточка «Задача 1» в колонке «Нужно сделать»"]
    assert feed[0]["actor"]["name"] == "Алия"
    older = bob.get(f"/boards/{team['id']}/activity", params={"before": feed[-1]["id"]}).json()
    assert [a["message"] for a in older][:2] == ["Новая карточка «Задача 0» в колонке «Нужно сделать»",
                                                 "Новый участник: Бауыржан"]


def test_health_and_docs_redirect(client):
    assert client.get("/health").json() == {"status": "ok"}
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 307 and root.headers["location"] == "/docs"


def test_cors_allows_frontend_and_client_id_header(client):
    response = client.options("/boards", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,x-client-id,content-type"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "x-client-id" in response.headers["access-control-allow-headers"].lower()
    stranger = client.options("/boards", headers={"Origin": "https://evil.example",
                                                  "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in stranger.headers
