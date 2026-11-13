"""Настоящие файлы для тестов загрузки — генерируются на лету."""
import io

from PIL import Image


def png(width: int = 64, height: int = 48, color: str = "teal") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, format="PNG")
    return out.getvalue()


def jpeg_rotated() -> bytes:
    """Снимок «с телефона»: 80×40, но в EXIF записано «повернуть на 90°»."""
    image = Image.new("RGB", (80, 40), "orange")
    exif = image.getexif()
    exif[0x0112] = 6  # Orientation: Rotate 90 CW
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def gif() -> bytes:
    out = io.BytesIO()
    Image.new("P", (10, 10)).save(out, format="GIF")
    return out.getvalue()


def webp() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(out, format="WEBP")
    return out.getvalue()


PDF = b"%PDF-1.4\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"
SVG_WITH_SCRIPT = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(document.cookie)</script></svg>'
