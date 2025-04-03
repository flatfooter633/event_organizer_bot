import logging
import os
from sys import stdout

from loguru import logger

# ---------------------------------------------------------
# Настройка loguru с ротацией и архивированием
# ---------------------------------------------------------

# Создаем папку log, если её нет
log_dir = "log"
os.makedirs(log_dir, exist_ok=True)

# Путь к файлу логов
log_file_path = os.path.join(log_dir, "async_app.log")

# Очищаем предыдущие обработчики loguru
logger.remove()

# Лог в файл с ротацией и сжатием
logger.add(
    log_file_path,
    level="INFO",
    rotation="10 MB",  # Ротация при достижении 10 MB
    compression="zip",  # Архивирование старых логов
    enqueue=True,  # Асинхронная запись через очередь
)

# Лог в консоль
logger.add(stdout, level="INFO", colorize=True)


# Перенаправление стандартного logging в loguru
class InterceptHandler(logging.Handler):
    def emit(self, record):
        level = record.levelname
        logger_opt = logger.opt(depth=6, exception=record.exc_info)
        logger_opt.log(level, record.getMessage())


# Настроим SQLAlchemy логгеры
sqlalchemy_loggers = [
    "sqlalchemy.engine.Engine",
    "sqlalchemy.pool",
    "sqlalchemy.dialects",
]

for log_name in sqlalchemy_loggers:
    logging.getLogger(log_name).handlers = [InterceptHandler()]
    logging.getLogger(log_name).propagate = False
    logging.getLogger(log_name).setLevel(logging.INFO)
