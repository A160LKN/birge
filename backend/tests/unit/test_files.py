"""Проверка файлов: тип по содержимому, имена, заголовки, превью, защита CSV."""
import io

import pytest
from PIL import Image

from app.errors import AppError
from app.jobs.tasks import _cell, make_thumbnail
from app.jobs.worker import PermanentJobError, backoff
from app.services.files import content_disposition, safe_filename, sniff
from tests import images

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("data", "extension", "content_type"), [
    (images.png(), ".png", "image/png"),
    (images.jpeg_rotated(), ".jpg", "image/jpeg"),
    (images.jpeg_rotated(), ".jpeg", "image/jpeg"),
    (images.gif(), ".gif", "image/gif"),
    (images.webp(), ".webp", "image/webp"),
    (images.PDF, ".pdf", "application/pdf"),
    ("Заметки по релизу\n".encode(), ".txt", "text/plain"),
    ("колонка;карточка\n".encode(), ".csv", "text/csv"),
    (b"# README\n", ".md", "text/markdown"),
])
def test_allowed_files_are_recognised_by_content(data, extension, content_type):
    assert sniff(data, extension).content_type == content_type


@pytest.mark.parametrize(("data", "extension", "code"), [
    (images.SVG_WITH_SCRIPT, ".svg", "unsupported_file"),   # SVG со скриптом — XSS, не принимаем
    (b"<html><script>alert(1)</script></html>", ".html", "unsupported_file"),
    (b"MZ\x90\x00\x03", ".exe", "unsupported_file"),
    (b"\x00\x01binary", ".txt", "unsupported_file"),     # «текст» с нулевыми байтами
    (b"\xff\xfe\xfa", ".txt", "unsupported_file"),        # не UTF-8
    (images.png(), ".jpg", "extension_mismatch"),         # PNG, названный JPEG
    (images.png(), ".txt", "extension_mismatch"),
    (images.PDF, ".png", "extension_mismatch"),
])
def test_dangerous_or_disguised_files_are_rejected(data, extension, code):
    with pytest.raises(AppError) as error:
        sniff(data, extension)
    assert error.value.status == 415 and error.value.code == code


@pytest.mark.parametrize(("raw", "safe"), [
    ("отчёт.pdf", "отчёт.pdf"),
    ("../../etc/passwd", "passwd"),
    ("C:\\Users\\a\\план.txt", "план.txt"),
    ("bad\x00name\n.txt", "bad_name_.txt"),
    ('a<b>:"c".png', "a_b_c_.png"),  # подряд идущие опасные символы — один «_»
    ("...", "file"),
    ("", "file"),
    (None, "file"),
    ("я" * 300 + ".png", "я" * 116 + ".png"),
])
def test_safe_filename(raw, safe):
    assert safe_filename(raw) == safe


def test_content_disposition_keeps_cyrillic_name():
    header = content_disposition("Отчёт «Q4».pdf", inline=False)
    assert header.startswith('attachment; filename="')
    assert "filename*=UTF-8''%D0%9E%D1%82%D1%87%D1%91%D1%82" in header
    assert header.encode("latin-1")  # заголовок HTTP должен быть в latin-1


def test_thumbnail_is_small_webp():
    thumb = Image.open(io.BytesIO(make_thumbnail(images.png(2000, 1000))))
    assert thumb.format == "WEBP"
    assert thumb.size == (480, 240)  # пропорции сохранены


def test_thumbnail_respects_exif_rotation():
    thumb = Image.open(io.BytesIO(make_thumbnail(images.jpeg_rotated())))
    assert thumb.size == (40, 80)  # фото с телефона не лежит на боку


def test_broken_image_is_a_permanent_failure():
    with pytest.raises(PermanentJobError):
        make_thumbnail(b"\x89PNG\r\n\x1a\n" + b"oops" * 10)


def test_decompression_bomb_is_rejected(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # картинка 64×48 > 2000 пикселей — уже «бомба»
    with pytest.raises(PermanentJobError):
        make_thumbnail(images.png(100, 100))


@pytest.mark.parametrize(("value", "expected"), [
    ("=HYPERLINK(\"http://evil\")", "'=HYPERLINK(\"http://evil\")"),
    ("+7 777", "'+7 777"), ("-1", "'-1"), ("@SUM(A1)", "'@SUM(A1)"),
    ("Обычный текст", "Обычный текст"), ("", ""),
])
def test_csv_cells_cannot_become_formulas(value, expected):
    assert _cell(value) == expected


def test_backoff_grows():
    assert [backoff(n).total_seconds() for n in (1, 2, 3)] == [2, 8, 32]
