import os
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def on_render() -> bool:
    """Render сам задаёт каждому сервису RENDER=true. По нему включаются настройки живого сайта:
    доверие к прокси Render и Cloudflare и запрет секретов по умолчанию. Явная переменная окружения
    по-прежнему важнее — значения по умолчанию лишь не дают забыть их в панели."""
    return os.environ.get("RENDER", "").lower() == "true"


class Settings(BaseSettings):
    """Настройки из переменных окружения (или файла .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # production — живой сайт: там значения по умолчанию из этого файла запрещены (см. no_dev_secrets_in_production)
    # На Render — production по умолчанию: живой сайт не должен зависеть от того, перенесли ли переменные
    # из render.yaml в панель (у сервиса, созданного не через Blueprint, они не применяются)
    environment: Literal["development", "test", "production"] = Field(
        default_factory=lambda: "production" if on_render() else "development")

    database_url: str = "postgresql+psycopg://birge:birge@localhost:5432/birge"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    jwt_secret: str = "dev-secret-change-me-in-production-32b"
    jwt_ttl_minutes: int = 12 * 60
    # Адреса фронтендов, которым браузер разрешит обращаться к API, через запятую
    cors_origins: str = "http://localhost:5173,http://localhost:4173"

    max_upload_bytes: int = 5 * 1024 * 1024
    # Фоновые задачи выполняются в том же процессе, что и API: на бесплатном хостинге один сервер.
    # В тестах обработчик выключен — задачи запускаются вручную и детерминированно.
    worker_enabled: bool = True
    worker_poll_seconds: float = 5.0
    job_lock_timeout_seconds: int = 300  # задача «зависла» дольше — её заберёт другой обработчик
    # События доски хранятся сутки: этого хватает, чтобы догнать пропущенное после обрыва связи
    event_retention_hours: int = 24
    ws_auth_timeout_seconds: float = 5.0
    # За прокси Render адрес клиента — в X-Forwarded-For. Локально заголовку не доверяем; на Render — доверяем
    trust_proxy: bool = Field(default_factory=on_render)
    # Сколько наших прокси дописывают адрес в конец X-Forwarded-For. На Render («…, клиент, Cloudflare») — 2
    proxy_hops: int = Field(default_factory=lambda: 2 if on_render() else 1)
    # Заголовок с адресом клиента от доверенного прокси. На Render — cf-connecting-ip: его ставит Cloudflare
    # на любом тарифе и перезаписывает, если клиент прислал свой.
    # Пусто — не используется: без такого прокси заголовок подделает кто угодно
    client_ip_header: str = Field(default_factory=lambda: "cf-connecting-ip" if on_render() else "")
    login_attempts: int = 5  # неудачных входов за 15 минут на пару «email + IP»
    registrations_per_hour: int = 10  # с одного IP
    timezone: str = "Asia/Almaty"  # время в выгрузке — местное, а не UTC

    @model_validator(mode="after")
    def no_dev_secrets_in_production(self) -> "Settings":
        """Секрет по умолчанию опубликован в репозитории: с ним любой подпишет себе токен.
        Забыли задать JWT_SECRET на живом сайте — сервер не стартует, а не работает с известным ключом."""
        if self.environment == "production" and (self.jwt_secret.startswith("dev-") or len(self.jwt_secret) < 32):
            raise ValueError("JWT_SECRET по умолчанию или короче 32 символов нельзя использовать в production")
        return self

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        """Хостинги выдают postgresql:// или postgres:// — указываем драйвер psycopg 3 явно."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url.removeprefix(prefix)
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
