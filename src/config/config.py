from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.orm import DeclarativeBase
import os

class DatabaseSettings(BaseSettings):
    DB_HOST: str = "localhost"
    DB_PORT: int = 8080
    DB_USER: str = "root"
    DB_PASS: str = "root"
    DB_NAME: str = "events.db"

    model_config = SettingsConfigDict(
        env_file=".env", populate_by_name=True, extra="allow"
    )

    @property
    def database_url_asyncpg(self):
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def database_url_psycopg(self):
        return f"postgresql+psycopg://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def database_url_sqlite(self):
        base_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..'))  # поднимаемся на уровень выше текущего файла
        db_path = os.path.join(base_dir, 'database', self.DB_NAME)
        return f"sqlite+aiosqlite:///{db_path}"


class Settings(BaseSettings):
    app_name: str = "Telegram Reminder Bot"
    database: DatabaseSettings = DatabaseSettings()
    BOT_TOKEN: str = "DEFAULT"
    SECRET_KEY: str = "DEFAULT"

    model_config = SettingsConfigDict(env_file="../.env", extra="allow")


settings = Settings()


# Создаем базовый класс для моделей
class Base(DeclarativeBase):
    pass
