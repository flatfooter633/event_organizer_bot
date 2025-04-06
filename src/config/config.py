from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.orm import DeclarativeBase
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # На один уровень выше текущего файла
ENV_PATH = BASE_DIR / ".env"

class DatabaseSettings(BaseSettings):
    DB_HOST: str = "postgres"
    DB_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str = "event_db"


    model_config = SettingsConfigDict(
        env_file=ENV_PATH, populate_by_name=True, extra="allow"
    )

    @property
    def database_url_asyncpg(self):
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.POSTGRES_DB}"

    @property
    def database_url_psycopg(self):
        return f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.POSTGRES_DB}"

    @property
    def database_url_sqlite(self):
        base_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..'))  # поднимаемся на уровень выше текущего файла
        db_path = os.path.join(base_dir, 'database', self.POSTGRES_DB)
        return f"sqlite+aiosqlite:///{db_path}"


class Settings(BaseSettings):
    app_name: str = "Telegram Reminder Bot"
    database: DatabaseSettings = DatabaseSettings()
    BOT_TOKEN: str = "DEFAULT"
    SECRET_KEY: str = "DEFAULT"

    model_config = SettingsConfigDict(
        env_file=ENV_PATH, extra="allow"
    )


settings = Settings()


# Создаем базовый класс для моделей
class Base(DeclarativeBase):
    pass
