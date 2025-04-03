from aiogram import Bot, Dispatcher
from sqlalchemy import select

from src.config.config import settings
from src.config.logger_config import logger
from src.database.database import init_db, get_db
from src.database.models import SystemSetting
from src.handlers.main_handlers import router as main_router
from src.handlers.service_handlers import router as service_router
from src.middleware.middleware import AdminAuthMiddleware, AdminCallbackMiddleware
from src.utils.scheduler import setup_scheduler

bot = Bot(token=settings.BOT_TOKEN)
dp = Dispatcher()


async def init_system_settings():
    """Инициализация системных настроек при первом запуске"""
    async with get_db() as session:
        # Список настроек для инициализации
        default_settings = [
            {
                "key": "VIDEO_FILE_ID",
                "value": "BAACAgIAAxkBAAIBbmfj4yKSZbFvWyPNLLBJu8eTzktYAAI_XQACLii5SMpj3AdHdHycNgQ",
                "description": "ID видео приветствия в Telegram",
            },
            {
                "key": "ADMIN_COMMANDS_TEXT",
                "value": "\n\n📢 <b>Рассылки:</b>"
                "\n\n - ✅ /broadcast - добавить"
                "\n\n\n📅 <b>Мероприятия:</b>"
                "\n\n - ✅ /add_event - добавить"
                "\n\n - 🚫 /cancel_event - отменить"
                "\n\n - ✏️ /edit_questions - редактир. анкеты"
                "\n\n - 🎬 /set_welcome_video - видео"
                "\n\n - 📤 /export_answers - выгрузка ответов"
                "\n\n - 🗂 /view_registrations - просмотр списков"
                "\n\n\n👨‍💻 <b>Админ-команды:</b>"
                "\n\n - 🥋 /add_admin - назначить админом"
                "\n\n - 🔐 /change_password - сменить пароль админа",
                "description": "Текст с описанием команд администратора",
            },
            {
                "key": "START_MESSAGE",
                "value": "Я — <b>Карина Богданова</b>, психолог, гештальт-терапевт и тренер.\n\n"
                "Уже почти 10 лет я веду частную практику и помогаю психологам выходить на стабильный поток клиентов.\n\n"
                "Здесь, в боте, тебя ждут 3 полезных видео, которые помогут уверенно стартовать в профессии:\n\n"
                "🎥 С чего начать психологу?\n\n"
                "🎥 Почему клиенты не приходят, даже если ты эксперт?\n\n"
                "🎥 Почему психологи с одинаковыми знаниями зарабатывают по-разному?\n\n\n",
                "description": "Стартовое сообщение бота",
            },
            {
                "key": "WELCOME_MESSAGE",
                "value": "💡 <b>Но сначала давай познакомимся!</b>\n\n"
                "Напиши цифру, которая ближе всего к твоей ситуации:\n\n"
                "1️⃣ Ещё учусь, но хочу начать консультировать\n"
                "2️⃣ Уже есть клиенты, но мало, хочу стабильный поток\n"
                "3️⃣ Работаю стабильно, но хочу зарабатывать больше\n\n"
                "<b>Жду твой ответ 👇 чтобы помочь тебе точечно 🔥</b>",
                "description": "Приветственное сообщение для новых пользователей",
            },
        ]

        # Запись настроек в базу, если их ещё нет
        for setting in default_settings:
            # Проверяем, существует ли настройка
            stmt = select(SystemSetting).where(SystemSetting.key == setting["key"])
            result = await session.execute(stmt)
            existing = result.scalars().first()

            if not existing:
                # Если настройки нет, создаем её
                new_setting = SystemSetting(
                    key=setting["key"],
                    value=setting["value"],
                    description=setting["description"],
                )
                session.add(new_setting)

        await session.commit()


async def main():
    """Запуск бота"""
    await init_db()
    await init_system_settings()

    dp.message.middleware(AdminAuthMiddleware())
    dp.update.middleware.register(AdminCallbackMiddleware())
    dp.callback_query.middleware(AdminCallbackMiddleware())

    dp.include_router(main_router)
    dp.include_router(service_router)

    scheduler = setup_scheduler(bot)
    if scheduler:
        logger.info("Планировщик запущен.")

    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка в работе бота: {e}")
    finally:
        logger.info("Остановка бота...")
        await logger.complete()  # Дождаться записи всех логов


if __name__ == "__main__":
    import asyncio

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")
