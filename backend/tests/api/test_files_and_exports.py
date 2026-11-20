"""Вложения, превью в фоне, подписанные ссылки, выгрузка в CSV."""
import csv
import io
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image
from sqlalchemy import text

from app.config import settings
from app.jobs import tasks
from app.services import files as files_service
from tests import images
from tests.conftest import sync_engine

pytestmark = pytest.mark.api


@pytest.fixture
def card(alice, team):
    return alice.card(team["columns"][0]["id"], "Макет")


def upload(user, card_id: int, name: str, data: bytes, content_type: str = "application/octet-stream"):
    return user.post(f"/cards/{card_id}/attachments", files={"file": (name, data, content_type)})


def test_image_upload_gets_thumbnail_in_background(client, alice, bob, card, run_jobs):
    response = upload(alice, card["id"], "макет.png", images.png(1200, 600), "image/png")
    assert response.status_code == 201
    attachment = response.json()
    assert (attachment["content_type"], attachment["thumbnail"], attachment["thumbnail_url"]) == (
        "image/png", "pending", None)

    assert run_jobs() == 1

    detail = bob.get(f"/cards/{card['id']}").json()
    (ready,) = detail["attachment_list"]
    assert ready["thumbnail"] == "ready"
    assert detail["attachments"] == 1 and detail["cover_url"] is not None  # у карточки появилась обложка
    thumb = client.get(ready["thumbnail_url"])  # подписанная ссылка — без токена, как из <img>
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"
    assert Image.open(io.BytesIO(thumb.content)).size == (480, 240)


def test_browser_content_type_is_ignored(alice, card):
    """Браузер прислал «image/png», а внутри PDF — верим содержимому."""
    response = upload(alice, card["id"], "отчёт.pdf", images.PDF, "image/png")
    assert response.status_code == 201
    assert response.json()["content_type"] == "application/pdf" and response.json()["thumbnail"] == "none"


@pytest.mark.parametrize(("name", "data", "code"), [
    ("logo.svg", images.SVG_WITH_SCRIPT, "unsupported_file"),
    ("photo.jpg", images.png(), "extension_mismatch"),
    ("setup.exe", b"MZ\x90\x00", "unsupported_file"),
])
def test_dangerous_uploads_are_rejected(alice, card, name, data, code):
    response = upload(alice, card["id"], name, data, "image/png")
    assert response.status_code == 415 and response.json()["error"]["code"] == code


def test_upload_size_limit(alice, card, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 1024)
    response = upload(alice, card["id"], "big.txt", b"x" * 1025)
    assert response.status_code == 413 and response.json()["error"]["code"] == "file_too_large"
    assert upload(alice, card["id"], "ok.txt", b"x" * 1024).status_code == 201


def test_empty_file(alice, card):
    assert upload(alice, card["id"], "empty.txt", b"").json()["error"]["code"] == "empty_file"


def test_attachment_limit(alice, card, monkeypatch):
    monkeypatch.setattr(files_service, "MAX_ATTACHMENTS_PER_CARD", 1)
    assert upload(alice, card["id"], "1.txt", b"one").status_code == 201
    assert upload(alice, card["id"], "2.txt", b"two").status_code == 409


def test_download_headers_protect_the_browser(client, alice, card):
    attachment = upload(alice, card["id"], "Заметки «релиз».txt", "Привет".encode()).json()
    response = client.get(attachment["url"])
    assert response.status_code == 200 and response.content == "Привет".encode()
    assert response.headers["content-disposition"].startswith("attachment;")  # текст — только скачиванием
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]


def test_images_open_inline(client, alice, card):
    attachment = upload(alice, card["id"], "фото.png", images.png()).json()
    assert client.get(attachment["url"]).headers["content-disposition"].startswith("inline;")


def test_tampered_or_missing_signature(client, alice, card, make_user):
    attachment = upload(alice, card["id"], "secret.txt", b"secret").json()
    url = urlparse(attachment["url"])
    params = parse_qs(url.query)
    other_file = f"/attachments/{attachment['id'] + 1}/file?{url.query}"
    longer = f"{url.path}?expires={int(params['expires'][0]) + 9999}&sig={params['sig'][0]}"
    for bad in (other_file, longer, f"{url.path}?expires={params['expires'][0]}&sig=forged"):
        assert client.get(bad).status_code in (403, 404)
    assert client.get(url.path).status_code == 401  # без подписи и без токена

    # По токену: участник — может, посторонний — 404
    assert alice.get(url.path).status_code == 200
    assert make_user().get(url.path).status_code == 404


def test_thumbnail_missing_for_non_images(alice, card):
    attachment = upload(alice, card["id"], "a.txt", b"text").json()
    assert alice.get(f"/attachments/{attachment['id']}/thumbnail").status_code == 404


def test_broken_image_marks_thumbnail_failed(alice, card, run_jobs):
    attachment = upload(alice, card["id"], "broken.png", b"\x89PNG\r\n\x1a\n" + b"garbage" * 20).json()
    run_jobs()
    (stored,) = alice.get(f"/cards/{card['id']}").json()["attachment_list"]
    assert stored["id"] == attachment["id"] and stored["thumbnail"] == "failed"


def test_delete_attachment(alice, bob, card, make_user):
    attachment = upload(alice, card["id"], "a.txt", b"text").json()
    assert make_user().delete(f"/attachments/{attachment['id']}").status_code == 404
    assert bob.delete(f"/attachments/{attachment['id']}").status_code == 204
    assert alice.get(f"/attachments/{attachment['id']}/file").status_code == 404


def test_attachment_deleted_before_thumbnail_job_runs(alice, card, run_jobs):
    attachment = upload(alice, card["id"], "a.png", images.png()).json()
    alice.delete(f"/attachments/{attachment['id']}")
    assert run_jobs() == 1  # задача не падает, а спокойно завершается


# ---------- Выгрузка ----------

def test_export_is_prepared_in_background(alice, bob, team, run_jobs):
    todo, doing, _ = (c["id"] for c in team["columns"])
    first = alice.card(todo, "Купить домен")
    alice.patch(f"/cards/{first['id']}", json={"version": 1, "assignee_id": bob.id, "due_date": "2026-12-31",
                                               "description": "=HYPERLINK(\"http://evil\")"})
    alice.card(doing, "Сверстать")

    requested = alice.post(f"/boards/{team['id']}/exports")
    assert requested.status_code == 202 and requested.json()["status"] == "pending"
    export_id = requested.json()["id"]
    assert alice.get(f"/exports/{export_id}/download").status_code == 409  # ещё не готово

    run_jobs()

    ready = alice.get(f"/exports/{export_id}").json()
    assert ready["status"] == "ready" and ready["filename"].endswith(".csv")
    response = alice.get(f"/exports/{export_id}/download")
    assert response.headers["content-type"].startswith("text/csv")
    assert response.content.startswith("﻿".encode())  # BOM для Excel
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0] == ["Колонка", "Карточка", "Описание", "Исполнитель", "Срок", "Комментариев", "Файлов",
                       "Изменена"]
    assert rows[1][:7] == ["Нужно сделать", "Купить домен", "'=HYPERLINK(\"http://evil\")",  # формула обезврежена
                           "Бауыржан", "31.12.2026", "0", "0"]
    almaty_now = datetime.now(UTC) + timedelta(hours=5)  # время — местное (Астана), а не UTC
    assert rows[1][7].startswith(almaty_now.strftime("%d.%m.%Y %H:"))
    assert rows[2][:2] == ["В работе", "Сверстать"]


def test_export_neutralises_formulas_in_every_text_field(alice, team, make_user, run_jobs):
    """Формулой может стать любой текст от пользователя: название колонки и имя исполнителя тоже."""
    mallory = make_user('=HYPERLINK("http://evil","Мария")')
    assert alice.post(f"/boards/{team['id']}/members", json={"email": mallory.email}).status_code == 201
    column = team["columns"][0]["id"]
    assert alice.patch(f"/columns/{column}", json={"title": "@SUM(1+1)"}).status_code == 200
    card = alice.card(column, "+7 777 000")
    alice.patch(f"/cards/{card['id']}", json={"version": 1, "assignee_id": mallory.id})

    export_id = alice.post(f"/boards/{team['id']}/exports").json()["id"]
    run_jobs()
    content = alice.get(f"/exports/{export_id}/download").content.decode("utf-8-sig")
    row = next(r for r in csv.reader(io.StringIO(content), delimiter=";") if r[1].endswith("777 000"))
    assert row[:2] == ["'@SUM(1+1)", "'+7 777 000"]
    assert row[3] == "'=HYPERLINK(\"http://evil\",\"Мария\")"


def test_export_belongs_to_the_person_who_requested_it(alice, bob, team, run_jobs):
    export_id = alice.post(f"/boards/{team['id']}/exports").json()["id"]
    run_jobs()
    assert bob.get(f"/exports/{export_id}").status_code == 404
    assert bob.get(f"/exports/{export_id}/download").status_code == 404


def test_stranger_cannot_request_export(alice, team, make_user):
    assert make_user().post(f"/boards/{team['id']}/exports").status_code == 404


def test_palette_gif_gets_thumbnail(alice, card, run_jobs):
    upload(alice, card["id"], "анимация.gif", images.gif())
    run_jobs()
    (stored,) = alice.get(f"/cards/{card['id']}").json()["attachment_list"]
    assert stored["thumbnail"] == "ready"


def test_failed_export_is_reported(alice, team, run_jobs, monkeypatch):
    async def broken(session, board_id):
        raise RuntimeError("диск переполнен")

    monkeypatch.setattr(tasks, "board_csv", broken)
    export_id = alice.post(f"/boards/{team['id']}/exports").json()["id"]
    for _ in range(3):  # три попытки с паузами — «проматываем» паузы
        run_jobs()
        with sync_engine.begin() as conn:
            conn.execute(text("UPDATE jobs SET run_at = now()"))
    assert alice.get(f"/exports/{export_id}").json()["status"] == "failed"
