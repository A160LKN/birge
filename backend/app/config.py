from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки из переменных окружения (или файла .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    timezone: str = "Asia/Almaty"  # время в выгрузке — местное, а не UTC

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
