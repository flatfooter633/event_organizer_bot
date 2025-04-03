from asyncio import Semaphore, gather
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.logger_config import logger
from src.database.database import get_db
from src.database.models import User, Event, Registration
from src.keyboards.keyboards import get_registration_kb

MAX_CONCURRENT_TASKS = 20  # ограничение на число одновременных отправок


async def notify_admins(bot: Bot, event: Event):
    async with get_db() as session:
        admins = await User.get_all_admins(session)
        for admin in admins:
            message_text = (
                f"🔔 <b>Событие завершено!</b>\n\n"
                f"📌 <b>Название:</b> {event.name}\n\n"
                f"🗓 <b>Дата:</b> {event.event_date.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"📖 <b>Описание:</b> <i>{event.description}</i>\n"
            )

            await safe_send_telegram(bot, admin.user_id, message_text)


async def send_reminder(
    bot: Bot, session: AsyncSession, event: Event, text: str, delta_days: int
):
    try:
        registered_users = set(
            await Registration.get_registered_users(session, event.id)
        )
        all_users = await User.get_all_user_ids(session)

        semaphore = Semaphore(MAX_CONCURRENT_TASKS)

        async def safe_send(user_id, message_text, keyboard):
            async with semaphore:
                await send_message_to_user(
                    bot, user_id, message_text, keyboard, event.name, delta_days
                )

        tasks = [
            safe_send(
                user_id,
                (
                    text
                    if user_id in registered_users
                    else f"{text}\n\nХотите зарегистрироваться?"
                ),
                None if user_id in registered_users else get_registration_kb(event.id),
            )
            for user_id in all_users
        ]
        await gather(*tasks)

    except Exception as e:
        logger.exception(
            f"Ошибка при отправке напоминаний для мероприятия (event_id={event.id})."
        )


async def safe_send_telegram(bot, chat_id, text, keyboard=None):
    try:
        await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=keyboard)
    except TelegramAPIError as e:
        logger.error(f"Ошибка отправления сообщения для {chat_id}: {e}")


async def send_message_to_user(
    bot: Bot,
    user_id: int,
    message_text: str,
    keyboard,
    event_name: str,
    delta_days: int,
):
    await safe_send_telegram(bot, user_id, message_text, keyboard)

    logger.info(
        f"Отправлено напоминание пользователю {user_id}, мероприятие {event_name} (через {delta_days} дней)."
    )


async def should_send_reminder(event: Event, reminder_type: str) -> bool:
    """Проверяет, было ли уже отправлено напоминание"""
    return not getattr(event, reminder_type)


async def mark_reminder_sent(session, event: Event, reminder_type: str):
    """Отмечает напоминание как отправленное и фиксирует изменения в БД"""
    setattr(event, reminder_type, True)
    await session.commit()


def russian_plural(n: int, variants: tuple[str, str, str]) -> str:
    if 10 <= n % 100 <= 20:
        return variants[2]
    if n % 10 == 1:
        return variants[0]
    if 2 <= n % 10 <= 4:
        return variants[1]
    return variants[2]


def format_time_difference(diff: timedelta) -> str:
    days = diff.days
    hours = diff.seconds // 3600
    minutes = (diff.seconds % 3600) // 60

    parts = []

    if days > 0:
        parts.append(f"{days} {russian_plural(days, ('день', 'дня', 'дней'))}")

    if hours > 0:
        parts.append(f"{hours} {russian_plural(hours, ('час', 'часа', 'часов'))}")

    if days == 0 and minutes > 0:  # минуты если менее одного дня осталось
        parts.append(
            f"{minutes} {russian_plural(minutes, ('минута', 'минуты', 'минут'))}"
        )

    return ", ".join(parts)


REMINDER_CONFIGS = [
    (timedelta(days=7), "reminder_week", "дней"),
    (timedelta(days=3), "reminder_3days", "дня"),
    (timedelta(hours=24), "reminder_day", "часа"),
    (timedelta(hours=7), "reminder_hours", "часов"),
    (timedelta(hours=4), "reminder_hour", "часа"),
]


async def send_event_reminders(bot, session, event, now):
    diff = event.event_date - now

    for interval, reminder_field, _ in REMINDER_CONFIGS:
        if interval >= diff > interval - timedelta(
            hours=2
        ) and await should_send_reminder(event, reminder_field):
            formatted_diff = format_time_difference(diff)
            message = (
                f"💡 <b>Мероприятие:</b> {event.name}\n\n"
                f"<i>{event.description}</i>\n\n"
                f"📅 <b>Дата:</b> {event.event_date:%d.%m.%Y %H:%M}\n\n"
                f"⏰ Начнется через {formatted_diff}!"
            )
            await send_reminder(bot, session, event, message, interval.days)
            await mark_reminder_sent(session, event, reminder_field)


# async def send_event_reminders(bot, session, event, now):
#     diff = event.event_date - now
#
#     for interval, reminder_field, unit in REMINDER_CONFIGS:
#         if interval >= diff > interval - timedelta(
#             hours=2
#         ) and await should_send_reminder(event, reminder_field):
#             count = diff.days if "дн" in unit else diff.seconds // 3600
#             message = (
#                 f"💡 <b>Мероприятие:</b> {event.name}\n\n"
#                 f"<i>{event.description}</i>\n\n"
#                 f"📅 <b>Дата:</b> {event.event_date:%d.%m.%Y %H:%M}\n\n"
#                 f"\n⏰ Начнется через {count} {unit}!"
#             )
#             await send_reminder(bot, session, event, message, interval.days)
#             await mark_reminder_sent(session, event, reminder_field)


# async def send_event_reminders(bot: Bot, session, event: Event, now: datetime):
#     """Отправляет напоминания пользователям в зависимости от времени до события"""
#     time_diff = event.event_date - now
#     diff_seconds = time_diff.total_seconds()
#     diff_minutes = diff_seconds // 60
#     diff_hours = diff_minutes // 60
#     diff_days = diff_hours // 24
#
#     event_data = (
#         f"💡 <b>Мероприятие:</b> {event.name}\n\n"
#         f"<i>{event.description}</i>\n\n"
#         f"📅 <b>Дата:</b> {event.event_date.strftime('%d.%m.%Y %H:%M')}\n\n"
#         f"\n⏰ Начнется через"
#     )
#
#     reminders = [
#         (
#             7 * 24 * 3600,
#             6 * 24 * 3600,
#             "reminder_week",
#             f"{event_data} {int(diff_days)} дней!",
#         ),
#         (
#             3 * 24 * 3600,
#             2 * 24 * 3600,
#             "reminder_3days",
#             f"{event_data} {int(diff_days)} дня!",
#         ),
#         (
#             24 * 3600,
#             23 * 3600,
#             "reminder_day",
#             f"{event_data} {int(diff_hours)} часов!",
#         ),
#         (6 * 3600, 5 * 3600, "reminder_hours", f"{event_data} {int(diff_hours)} часов!"),
#         (3 * 3600, 2 * 3600, "reminder_hour", f"{event_data} {int(diff_hours)} часа!"),
#     ]
#
#     for start, end, reminder_field, message in reminders:
#         if start >= diff_seconds > end and await should_send_reminder(
#             event, reminder_field
#         ):
#             try:
#                 await send_reminder(bot, session, event, message, 1)
#                 await mark_reminder_sent(session, event, reminder_field)
#             except Exception as e:
#                 logger.exception(
#                     f"Ошибка при отправке напоминаний для события {event.id}: {str(e)}"
#                 )


async def check_events(bot: Bot):
    """Проверяет события и отправляет напоминания"""
    now = datetime.now()
    async with get_db() as session:
        events = await Event.get_active_events(session)  # Новый метод
        for event in events:
            await send_event_reminders(bot, session, event, now)

            if now > event.event_date + timedelta(hours=1):
                event.status = "completed"
                await notify_admins(bot, event)
                await session.commit()
                logger.info(f"Событие '{event.name}' отмечено завершенным.")


def setup_scheduler(bot: Bot):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_events,
        "interval",
        minutes=20,
        args=[bot],
        next_run_time=datetime.now() + timedelta(seconds=10),
    )
    scheduler.start()
    logger.info("Планировщик задач успешно настроен и запущен.")
    return scheduler
