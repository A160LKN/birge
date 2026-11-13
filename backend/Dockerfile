FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Сначала зависимости — этот слой кешируется и не пересобирается при каждой правке кода
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app
COPY migrations migrations
COPY alembic.ini .
COPY scripts/start.sh scripts/start.sh

# Приложение не работает от root
RUN useradd --create-home birge
USER birge

EXPOSE 8000
CMD ["sh", "scripts/start.sh"]
