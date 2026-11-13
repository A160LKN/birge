"""Схема API для фронтенда: python scripts/export_openapi.py ../frontend/src/api/openapi.json"""
import json
import sys

from app.main import app

with open(sys.argv[1], "w", encoding="utf-8") as out:
    json.dump(app.openapi(), out, ensure_ascii=False, indent=2)
    out.write("\n")
