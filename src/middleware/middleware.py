import asyncio

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, TelegramObject, CallbackQuery

from src.config.logger_config import logger
from src.database.database import get_db
from src.database.models import check_admin_cached
from src.states.states import AdminAuth



def log_user_action(user_id: int, action: str, his: bool = False):
    logger.info(f"{"Пользователь" if not his else "Пользователю"}  {user_id} {action}")


async def async_log_user_action(user_id: int, action: str, his: bool = False):
    await asyncio.to_thread(
        log_user_action,
        user_id,
        action,
        his=his,
    )




# ---------------------------------------------------------
# region AdminCallbackMiddleware
# ---------------------------------------------------------

class AdminCallbackMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data):
        # Проверяем, что это callback_query и начинается с префикса админ-команд
        if (
                isinstance(event, CallbackQuery)
                and event.data
                and event.data.startswith("command_")
        ):
            user_id = event.from_user.id
            async with get_db() as session:
                is_admin = await check_admin_cached(session, user_id)
                if not is_admin:
                    logger.warning(
                        f"❌ У пользователя {user_id} нет прав администратора для вызова callback {event.data}."
                    )
                    await event.answer("🚫 Доступ запрещен.", show_alert=True)
                    return  # Не продолжаем обработку

                await async_log_user_action(
                    event.from_user.id,
                    f"начал выполнение админ-команды {event.data}. 🔐 Запрошен пароль администратора.",
                    his=False,
                )

                # Сохраняем информацию в состоянии
                state: FSMContext = data["state"]
                await state.update_data(
                    original_callback=event.data,
                    # Сохраняем данные, необходимые для воссоздания CallbackQuery
                    callback_chat_id=event.message.chat.id,
                    callback_message_id=event.message.message_id,
                    callback_user_id=event.from_user.id,
                    callback_username=event.from_user.username,
                    callback_first_name=event.from_user.first_name,
                    callback_last_name=event.from_user.last_name,
                )
                await state.set_state(AdminAuth.password)  # Запрашиваем пароль

                await event.answer("🔑 Введите пароль администратора:", show_alert=True)
                return  # Прерываем дальнейшую обработку до ввода пароля

        # Если проверки не сработали, передаем управление дальше
        return await handler(event, data)


# endregion
# ---------------------------------------------------------
