import io
from collections import defaultdict
from datetime import datetime, UTC
from typing import Union

from openpyxl import Workbook

from aiogram import Bot, types, F, Router
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramRetryAfter,
    TelegramNetworkError,
)
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram_calendar.dialog_calendar import (
    DialogCalendarCallback,
    DialogCalendar,
    DialogCalAct,
)
from src.config.config import settings
from src.config.logger_config import logger
from src.database.database import get_db
from src.database.models import User, Event, Registration, Answer, Question, SystemSetting, BroadcastQueue
from src.database.models import (
    get_cached_event_by_id,
    get_cached_active_events,
    get_cached_questions,
    clear_event_from_cache,
    clear_all_cache,
    check_admin_cached,
)
from src.keyboards.keyboards import (
    get_events_kb,
    active_events_kb,
    get_broadcast_confirmation_kb,
    get_cancel_confirmation_kb,
    create_question_keyboard,
    create_time_keyboard,
    edit_setting_keyboard, get_reschedule_confirmation_kb
)
from src.states.states import (
    AddEvent,
    ViewRegistrations,
    AddQuestionsToEvent,
    AddAdmin,
    AdminAuth,
    CancelEvent,
    ExportAnswers,
    ChangePassword,
    BroadcastMessage,
    SetWelcomeVideo,
    RescheduleEvent,
    EditQuestions,
    AdminStates,
)
from src.utils.scheduler import notify_admins

router = Router()

MAX_QUESTIONS = settings.MAX_QUESTIONS
# ---------------------------------------------------------
# region RescheduleEvent(StatesGroup)
# ---------------------------------------------------------
@router.callback_query(F.data == "command_reschedule_event")
async def reschedule_event(callback: types.CallbackQuery, state: FSMContext):
    # Отвечаем на колбэк, чтобы убрать индикатор загрузки с кнопки
    await callback.answer()

    logger.info(f"Админ {callback.from_user.id} начал процесс переноса мероприятия.")

    async with get_db() as session:
        events = await get_cached_active_events(session)

        if events:
            await callback.message.answer(
                "Выберите мероприятие, дату которого требуется перенести:",
                reply_markup=get_events_kb(events)
            )

            await state.set_state(RescheduleEvent.choosing_event)

            logger.info(
                f"Отправлен список мероприятий админу {callback.from_user.id} для переноса."
            )
        else:
            await callback.message.answer("🔴 Нет активных мероприятий.")


@router.callback_query(RescheduleEvent.choosing_event)
async def process_event_selection(callback: types.CallbackQuery, state: FSMContext):
    # Извлекаем ID из строки вида 'event_3'
    event_id_str = callback.data.split('_')[1] if '_' in callback.data else callback.data

    try:
        event_id = int(event_id_str)
    except ValueError:
        await callback.message.answer("Ошибка: некорректный формат ID мероприятия.")
        return

    async with get_db() as session:
        event = await session.get(Event, event_id)
        if not event:
            await callback.message.answer("Мероприятие не найдено. Попробуйте снова.")
            return

        await state.update_data(event_id=event_id, event_name=event.name)
        logger.info(f"Админ {callback.from_user.id} выбрал мероприятие '{event.name}' для переноса")

        # Показываем текущую дату мероприятия и предлагаем выбрать новую
        current_date_str = event.event_date.strftime('%d.%m.%Y %H:%M')
        await callback.message.edit_text(
            f"Выбрано мероприятие: {event.name}\n"
            f"Текущая дата: {current_date_str}\n\n"
            "Выберите новую дату:",
            reply_markup=await DialogCalendar(locale="ru_RU", show_alerts=True).start_calendar()
        )

        await state.set_state(RescheduleEvent.choosing_date)

    await callback.answer()



# Обработчик выбора даты из календаря
@router.callback_query(DialogCalendarCallback.filter(), RescheduleEvent.choosing_date)
async def process_date_selection(
        callback: types.CallbackQuery,
        callback_data: DialogCalendarCallback,
        state: FSMContext,
):
    calendar = DialogCalendar(locale="ru_RU", show_alerts=True)
    selected, date_value = await calendar.process_selection(callback, callback_data)

    # Если была нажата кнопка отмены
    if callback_data.act == DialogCalAct.cancel:
        await state.clear()
        await callback.message.edit_text("🚫 Перенос мероприятия отменен.")
        await callback.answer("🚫 Перенос мероприятия отменен.", show_alert=True)
        return

    if selected:
        if date_value:
            await state.update_data(selected_date=date_value)

            await callback.message.edit_text(
                f"Вы выбрали дату: {date_value.strftime('%d.%m.%Y')}\nТеперь выберите время:",
                reply_markup=create_time_keyboard()
            )

            await state.set_state(RescheduleEvent.choosing_time)
    else:
        # Если дата не была выбрана, но это не отмена - это просто навигация по календарю
        await callback.answer(
            "Пожалуйста, выберите дату"
            if callback_data.act != DialogCalAct.cancel
            else None
        )


# Обработчик выбора времени
@router.callback_query(F.data.startswith("time_"), RescheduleEvent.choosing_time)
async def process_time_selection(callback: types.CallbackQuery, state: FSMContext):
    time_str = callback.data.split("_")[1]
    try:
        selected_time = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        await callback.answer("Некорректное время. Попробуйте снова.")
        return

    data = await state.get_data()
    selected_date = data["selected_date"]
    full_datetime = datetime.combine(selected_date, selected_time)
    event_name = data["event_name"]

    await state.update_data(new_date=full_datetime)

    # Запрашиваем подтверждение перед изменением даты
    await callback.message.edit_text(
        f"Вы собираетесь перенести мероприятие:\n"
        f"'{event_name}'\n\n"
        f"на новую дату: {full_datetime.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Подтвердите действие:",
        reply_markup=get_reschedule_confirmation_kb()
    )

    await state.set_state(RescheduleEvent.confirmation)
    await callback.answer()


# Обработчик подтверждения переноса
@router.callback_query(F.data == "confirm_reschedule", RescheduleEvent.confirmation)
async def confirm_reschedule(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()

    data = await state.get_data()
    event_id = data["event_id"]
    new_date = data["new_date"]
    now = datetime.now()
    if new_date <= now:
        await callback.message.edit_text("Ошибка: нельзя перенести мероприятие на прошедшую дату.")
        await state.clear()
        return

    async with get_db() as session:
        event = await session.get(Event, event_id)
        if not event:
            await callback.message.edit_text("Ошибка: мероприятие не найдено.")
            await state.clear()
            return

        # Сохраняем старую дату для логов
        old_date = event.event_date

        if event.event_date == new_date:
            await callback.message.edit_text("Новая дата совпадает с текущей. Перенос не требуется.")
            await state.clear()
            return

        # Обновляем дату мероприятия
        event.event_date = new_date
        await session.commit()

        # Очищаем кэш
        clear_all_cache()

        logger.info(
            f"Админ {callback.from_user.id} перенес мероприятие '{event.name}' "
            f"с {old_date.strftime('%d.%m.%Y %H:%M')} на {new_date.strftime('%d.%m.%Y %H:%M')}"
        )

        # Уведомляем зарегистрированных пользователей о переносе
        await notify_users_about_reschedule(bot, event, old_date)

    await callback.message.edit_text(
        f"✅ Мероприятие успешно перенесено на {new_date.strftime('%d.%m.%Y %H:%M')}."
    )

    await state.clear()


# Обработчик отмены переноса
@router.callback_query(F.data == "cancel_reschedule", RescheduleEvent.confirmation)
async def cancel_reschedule(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("🚫 Перенос мероприятия отменен.")
    await state.clear()


# Функция для отправки уведомлений о переносе мероприятия
async def notify_users_about_reschedule(bot: Bot, event: Event, old_date: datetime):
    """⚠️ Сообщаем вам, Игорь, что у нас изменения в расписании.

Мероприятие 'Семинар' перенесено по техническим причинам.

Старая дата: 16.05.2025 17:00
Новая дата: 17.05.2025 13:00

Ваша регистрация сохраняется. Будем рады встрече в вами."""
    async with get_db() as session:
        # Получаем всех зарегистрированных пользователей с дополнительной информацией
        registrations = await Registration.get_registrations_info(session, event.id)

        # Форматируем даты
        old_date_str = old_date.strftime("%d.%m.%Y %H:%M")
        new_date_str = event.event_date.strftime("%d.%m.%Y %H:%M")

        # Отправляем уведомления всем зарегистрированным пользователям
        for reg in registrations:
            try:
                # Используем имя пользователя в сообщении для большей персонализации
                await bot.send_message(
                    chat_id=reg.user_id,
                    text=f"⚠️️ Сообщаем вам, {reg.first_name}, что у нас изменения в расписании.\n\n"
                         f"Мероприятие '<b>{event.name}</b>' перенесено по техническим причинам.\n\n"
                         f"📅 <b>Старая дата:</b> {old_date_str}\n\n"
                         f"📆 <b>Новая дата:</b> {new_date_str}\n\n"
                         f"Ваша регистрация сохраняется. Будем рады встрече в вами.",
                    parse_mode="HTML"
                )
                logger.info(
                    f"Отправлено уведомление о переносе мероприятия пользователю {reg.user_id} ({reg.first_name} {reg.last_name})")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления пользователю {reg.user_id}: {e}")

        # Логируем общую информацию
        logger.info(f"Отправлены уведомления о переносе мероприятия '{event.name}' {len(registrations)} пользователям")


# endregion
# ---------------------------------------------------------



async def notify_all_users(bot: Bot, event: Event):
    async with get_db() as session:
        users = await User.get_all_users(session)
        events = await get_cached_active_events(session)

    for user_id in users:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    f"⚠️ <b>Новое мероприятие:</b> {event.name}\n\n"
                    f"<i>{event.description}</i>\n\n"
                    f"📅 <b>Дата:</b> {event.event_date.strftime('%d.%m.%Y %H:%M')}\n\n"
                    "👇🏼 Зарегистрируйтесь, чтобы принять участие! 👇🏼"
                ),
                parse_mode="HTML",
                reply_markup=active_events_kb(events),
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")


# ---------------------------------------------------------
# region AdminAuth(StatesGroup)
# ---------------------------------------------------------
# Обработка команд из callback-запросов
async def handle_callback_command(command, callback, state):
    commands_map = {
        "broadcast": broadcast,
        "add_event": add_event,
        "reschedule_event": reschedule_event,
        "cancel_event": cancel_event,
        "edit_questions": edit_questions,
        "set_welcome_video": set_welcome_video,
        "export_answers": export_answers,
        "view_registrations": view_registrations,
        "add_admin": add_admin,
        "change_password": change_password,
        "edit_settings": edit_settings,
    }

    command_handler = commands_map.get(command)
    if command_handler:
        # Теперь передаём объект, похожий на CallbackQuery
        await command_handler(callback, state)
    else:
        # Если callback - это фейковый объект, у него будет message
        await callback.message.answer("🚫 Callback-команда не распознана.")




@router.message(AdminAuth.password, F.text)
async def check_admin_password(message: Message, state: FSMContext):
    async with get_db() as session:
        user = await session.get(User, message.from_user.id)

        if user and user.verify_password(message.text):
            data = await state.get_data()
            original_callback = data.get("original_callback")

            # Создаём фейковый объект CallbackQuery на основе сохранённых данных
            if original_callback and original_callback.startswith("command_"):
                # Формируем команду из callback data
                command = original_callback.split("command_")[1]

                # Создаём фейковый объект CallbackQuery
                from aiogram.types import User as AiogramUser

                class FakeCallbackQuery:
                    def __init__(self, data_dict):
                        self.data = original_callback
                        self.message = message

                        # Восстанавливаем объект from_user
                        from_user_data = {
                            "id": data_dict.get("callback_user_id"),
                            "username": data_dict.get("callback_username"),
                            "first_name": data_dict.get("callback_first_name"),
                            "last_name": data_dict.get("callback_last_name"),
                            "is_bot": False
                        }
                        self.from_user = AiogramUser(**{k: v for k, v in from_user_data.items() if v is not None})

                    async def answer(self, text=None, show_alert=False):
                        # Имитация метода answer
                        pass

                # Создаём фейковый объект для использования в обработчиках
                fake_callback = FakeCallbackQuery(data)

                # Теперь вызываем обработчик с фейковым CallbackQuery
                await handle_callback_command(command, fake_callback, state)
                try:
                    await message.delete()  # Удаляем сообщение с паролем
                except Exception as e:
                    logger.warning(f"Не удалось удалить сообщение: {e}")

                return

            await state.clear()
        else:
            await message.delete()  # Удаляем сообщение с паролем
            await message.answer("❌ Неверный пароль! Попробуйте снова:")



# endregion
# ---------------------------------------------------------



# ---------------------------------------------------------
# region Command("edit_settings")
# ---------------------------------------------------------
@router.callback_query(F.data == "command_edit_settings")
async def edit_settings(callback: types.CallbackQuery, state: FSMContext):
    # Получаем данные из колбэка
    first_name = callback.from_user.first_name

    # Отвечаем на колбэк (чтобы убрать часы загрузки на кнопке)
    await callback.answer()

    # Показываем клавиатуру с настройками для редактирования
    await callback.message.delete()
    await callback.message.answer(
        f"{first_name}, выберите настройку для редактирования:",
        reply_markup=edit_setting_keyboard,
    )



@router.callback_query(F.data.startswith("edit_setting_"))
async def begin_edit_setting(query: types.CallbackQuery, state: FSMContext):
    setting_key = query.data.replace("edit_setting_", "")
    user_id = query.from_user.id
    async with get_db() as session:
        admin = await check_admin_cached(session, user_id)

    if not admin:
        await query.message.delete()
        await query.answer(f"🚫 У вас нет прав администратора.", show_alert=True)
        return

    async with get_db() as session:
        setting = await SystemSetting.get_setting(session, setting_key, "")

    await state.update_data(edit_setting_key=setting_key)
    await query.answer(f"Вы выбрали редактирование настройки '{setting_key}'")
    if setting_key == "VIDEO_FILE_ID" and setting:

        # Отправляем видео, если оно есть
        await query.message.delete()
        await query.message.answer_video(
            video=setting,
            caption="⚙️ Текущее приветственное видео\n\n"
                    "🖊 Загрузите новое видео или нажмите /cancel для отмены:"
        )
        await state.set_state(AdminStates.edit_video_setting)
    else:
        await state.set_state(AdminStates.edit_setting)
        await query.message.edit_text(
            f"⚙️ Текущее значение настройки '{setting_key}':\n\n"
            f"🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽\n\n"
            f"{setting}\n\n"
            f"🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽\n\n"
            f"🖊 Введите новое значение или /cancel для отмены:"
        )

@router.message(AdminStates.edit_video_setting)
async def save_video_setting(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.delete()
        await message.answer("⚠️ Редактирование отменено.")
        return

    if not message.video:
        await message.answer(
            "Пожалуйста, загрузите видеофайл или нажмите /cancel для отмены."
        )
        return

    data = await state.get_data()
    setting_key = data.get("edit_setting_key")

    # Получаем file_id загруженного видео
    video_file_id = message.video.file_id

    async with get_db() as session:
        await SystemSetting.set_setting(session, setting_key, video_file_id)

    await message.answer(f"✅ Приветственное видео успешно обновлено!")
    await state.clear()


@router.message(AdminStates.edit_setting)
async def save_setting(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.delete()
        await message.answer("⚠️ Редактирование отменено.")
        return

    data = await state.get_data()
    setting_key = data.get("edit_setting_key")

    async with get_db() as session:
        await SystemSetting.set_setting(session, setting_key, message.text)

    await message.answer(f"✅ Настройка '{setting_key}' успешно обновлена!")
    await state.clear()



# endregion
# ---------------------------------------------------------


# ---------------------------------------------------------
# region AddEvent(StatesGroup)
# ---------------------------------------------------------
@router.callback_query(F.data == "command_add_event")
async def add_event(callback: types.CallbackQuery, state: FSMContext):
    # Отвечаем на колбэк, чтобы убрать индикатор загрузки с кнопки
    await callback.answer()

    # Логируем действие
    logger.info(f"Админ {callback.from_user.id} начал добавление мероприятия.")

    # Отправляем сообщение с инструкцией
    await callback.message.answer("Введите название мероприятия:")

    # Устанавливаем состояние
    await state.set_state(AddEvent.name)



@router.message(AddEvent.name)
async def event_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    logger.info(
        f"Админ {message.from_user.id} ввел название мероприятия: {message.text}"
    )
    await message.answer("Введите описание мероприятия.")
    await state.set_state(AddEvent.description)


@router.message(AddEvent.description)
async def event_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    logger.info(f"Админ {message.from_user.id} ввел описание мероприятия")
    await message.answer(
        "Выберите дату:",
        reply_markup=await DialogCalendar(
            locale="ru_RU", show_alerts=True
        ).start_calendar(),
    )

    await state.set_state(AddEvent.choosing_date)


# Обработчик выбора даты из календаря
@router.callback_query(DialogCalendarCallback.filter(), AddEvent.choosing_date)
async def process_date_selection(
    callback: types.CallbackQuery,
    callback_data: DialogCalendarCallback,
    state: FSMContext,
):
    calendar = DialogCalendar(locale="ru_RU", show_alerts=True)
    selected, date_value = await calendar.process_selection(callback, callback_data)

    # Если была нажата кнопка отмены, метод process_selection вернет (False, None),
    # и при этом удалит клавиатуру с календарем
    if callback_data.act == DialogCalAct.cancel:
        await state.clear()
        await callback.message.edit_text("🚫 Создание мероприятия отменено.")
        await callback.answer("🚫 Создание мероприятия отменено.", show_alert=True)
        return

    if selected:
        if date_value:
            await state.update_data(selected_date=date_value)

            await callback.message.edit_text(
                f"Вы выбрали дату: {date_value.strftime('%d.%m.%Y')}\nТеперь выберите время:",
                reply_markup=create_time_keyboard(),
            )

            await state.set_state(AddEvent.choosing_time)
    else:
        # Если дата не была выбрана, но это не отмена - это просто навигация по календарю
        await callback.answer(
            "Пожалуйста, выберите дату"
            if callback_data.act != DialogCalAct.cancel
            else None
        )


# Обработчик выбора времени
@router.callback_query(F.data.startswith("time_"), AddEvent.choosing_time)
async def process_time_selection(callback: types.CallbackQuery, state: FSMContext):
    time_str = callback.data.split("_")[1]
    try:
        selected_time = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        await callback.answer("Некорректное время. Введите вручную в формате ЧЧ:ММ.")
        return

    data = await state.get_data()
    selected_date = data["selected_date"]
    full_datetime = datetime.combine(selected_date, selected_time)
    await state.update_data(date=full_datetime)
    logger.info(
        f"Админ {callback.from_user.id} установил дату мероприятия через inline-кнопки: {full_datetime.strftime('%Y-%m-%d %H:%M')}"
    )

    await callback.message.edit_text(
        f"Вы выбрали: {full_datetime.strftime('%Y-%m-%d %H:%M')}\n"
        "Теперь напишите вопрос анкеты для участников (или отправьте команду /done для завершения):"
    )
    await state.set_state(AddEvent.question)
    await callback.answer()



@router.message(AddEvent.question, Command("done"))
async def finish_questions(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    async with get_db() as session:
        # Создание мероприятия
        event = await Event.add_event(
            session, data["name"], data["description"], data["date"]
        )

        questions = data.get("questions", [])
        # Добавляем вопросы без метода create
        for order, question_text in enumerate(questions, start=1):
            question = Question(
                event_id=event.id,
                question_text=question_text,
                order=order,
            )
            session.add(question)

        await session.commit()
        clear_all_cache()

    # Уведомляем пользователей о новом мероприятии
    await notify_all_users(bot, event)

    # Сообщение админу
    await message.answer("Мероприятие и вопросы были успешно добавлены! ✅")
    await state.clear()





@router.message(AddEvent.question, F.text)
async def add_question(message: Message, state: FSMContext):
    data = await state.get_data()
    questions = data.get("questions", [])

    if len(questions) >= MAX_QUESTIONS:
        await message.answer(
            f"🔴 Невозможно добавить вопрос! Максимальное количество вопросов — {MAX_QUESTIONS}. "
            "Отправьте /done для завершения создания мероприятия."
        )
        return

    questions.append(message.text)

    await state.update_data(questions=questions)

    if len(questions) < MAX_QUESTIONS:
        await message.answer(
            f"✅ Вопрос ({len(questions)}/{MAX_QUESTIONS}) добавлен! Напишите следующий или отправьте /done."
        )
    else:
        await message.answer(
            f"✅ Вопрос ({len(questions)}/{MAX_QUESTIONS}) добавлен. "
            "Вы достигли максимального лимита вопросов. Отправьте /done, чтобы сохранить мероприятие."
        )


# endregion
# ---------------------------------------------------------


# ---------------------------------------------------------
# region EditQuestions(StatesGroup)
# ---------------------------------------------------------
@router.callback_query(F.data == "command_edit_questions")
async def edit_questions(callback: types.CallbackQuery, state: FSMContext):
    # Отвечаем на колбэк, чтобы убрать индикатор загрузки с кнопки
    await callback.answer()

    # Получаем список активных мероприятий из базы данных
    async with get_db() as session:
        events = await get_cached_active_events(session)

        # Отправляем сообщение с выбором мероприятия
        await callback.message.answer(
            "Выберите мероприятие:",
            reply_markup=get_events_kb(events)
        )

        # Устанавливаем состояние для FSM
        await state.set_state(EditQuestions.EVENT)



@router.callback_query(EditQuestions.EVENT, lambda c: c.data.startswith("event_"))
async def select_question_to_edit(callback: types.CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[1])
    await callback.answer()

    async with get_db() as session:
        questions = await get_cached_questions(session, event_id)

    await state.update_data(event_id=event_id)

    if questions:
        keyboard = create_question_keyboard(questions)
        await callback.message.edit_text(
            "Выберите вопрос для редактирования:", reply_markup=keyboard
        )
        await state.set_state(EditQuestions.QUESTION)

    else:
        await callback.message.edit_text(
            "❗ У данного мероприятия пока нет вопросов. Давайте их добавим!"
        )
        await state.update_data(questions=[])
        await callback.message.answer(
            "📝 Отправьте первые вопросы по одному сообщению.\n"
            f"Максимальное количество вопросов: {MAX_QUESTIONS}.\n"
            "Напишите /done чтобы закончить добавление вопросов."
        )
        await state.set_state(AddQuestionsToEvent.question)


# Сначала явный обработчик команды /done
@router.message(StateFilter(AddQuestionsToEvent.question), Command("done"))
async def finish_adding_questions_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    questions = data.get("questions", [])
    event_id = data["event_id"]

    if questions:
        async with get_db() as session:
            for order, question_text in enumerate(questions, 1):
                session.add(
                    Question(
                        event_id=event_id, question_text=question_text, order=order
                    )
                )
            await session.commit()

        await message.answer(f"✅ Успешно добавлено {len(questions)} вопросов.")
        await state.clear()
    else:
        await message.answer("❌ Вы не добавили ни одного вопроса.")
        await state.clear()


# Затем добавляем явное исключение команды /done и проверку лимита
@router.message(
    StateFilter(AddQuestionsToEvent.question),
    F.text,
    ~Command("done"),  # Исключение - чтобы этот хендлер НЕ срабатывал на команду /done
)
async def add_question_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    questions = data.get("questions", [])
    question_text = message.text.strip()

    if not question_text:
        await message.answer("❗️ Вопрос не может быть пустым. Попробуйте еще раз.")
        return

    if len(questions) >= MAX_QUESTIONS:
        await message.answer(
            f"🔴 Достигнут лимит вопросов ({MAX_QUESTIONS}). Используйте /done для завершения."
        )
        return

    questions.append(question_text)
    await state.update_data(questions=questions)

    await message.answer(
        f"✅ Вопрос добавлен ({len(questions)}/{MAX_QUESTIONS}). "
        "Отправьте следующий вопрос или /done."
    )


@router.callback_query(EditQuestions.QUESTION)
async def edit_question_text(callback: types.CallbackQuery, state: FSMContext):
    question_id = int(callback.data.split("_")[1])

    # Получаем вопрос из БД через SQLAlchemy session.get()
    async with get_db() as session:
        question = await session.get(Question, question_id)

    current_text = question.question_text if question else "❗️Текст вопроса не найден."

    await callback.answer(f"Редактирование вопроса {question_id}")

    await state.update_data(question_id=question_id)

    # Отображаем старый текст и просим вписать новый
    await callback.message.edit_text(
        f"❔ Текущий текст вопроса:\n\n"
        f"<i>{current_text}</i>\n\n"
        f"📝 Введите новый текст вопроса:",
        parse_mode="HTML",
    )

    await state.set_state(EditQuestions.TEXT)


@router.message(EditQuestions.TEXT)
async def save_question_text(message: Message, state: FSMContext):
    data = await state.get_data()
    async with get_db() as session:
        await Question.update_question(session, data["question_id"], message.text)
        logger.info(
            f"Вопрос {data['question_id']} был обновлен пользователем {message.from_user.id}. Новый текст: {message.text}"
        )
        clear_all_cache()
    await message.answer("✅ Вопрос обновлен!")
    await state.clear()

# endregion
# ---------------------------------------------------------


# ---------------------------------------------------------
# region Command("export_answers")
# ---------------------------------------------------------
@router.callback_query(F.data == "command_export_answers")
async def export_answers(callback: types.CallbackQuery, state: FSMContext):
    # Отвечаем на колбэк, чтобы убрать индикатор загрузки с кнопки
    await callback.answer()

    logger.info(f"Админ {callback.from_user.id} начал экспортирование ответов.")

    async with get_db() as session:
        events = await Event.get_active_events_with_questions_and_answers(session)

        if not events:
            await callback.message.answer("Нет активных мероприятий с заданными вопросами.")
            return

        await state.set_state(ExportAnswers.event)  # устанавливаем состояние

        await callback.message.answer(
            "Выберите мероприятие:",
            reply_markup=get_events_kb(events)
        )

        logger.info(
            f"Отправлен список мероприятий админу {callback.from_user.id} для экспорта ответов."
        )

@router.callback_query(ExportAnswers.event, lambda c: c.data.startswith("event_"))
async def process_export(callback: types.CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[1])

    async with get_db() as session:
        event = await get_cached_event_by_id(session, event_id)

        # Получаем ответы с уже отсортированными вопросами
        answers = await Answer.get_answers_for_event(session, event_id)

    # Группируем ответы по User ID
    data = defaultdict(dict)
    sorted_questions = []  # Список вопросов в нужном порядке

    for user_id, question_text, answer_text in answers:
        data[user_id][question_text] = answer_text
        if question_text not in sorted_questions:
            sorted_questions.append(
                question_text
            )  # Добавляем вопросы в порядке их появления

    # Создаем рабочую книгу и лист Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "Ответы"

    # Заполняем заголовки таблицы
    headers = ["User ID"] + sorted_questions
    ws.append(headers)

    # Заполняем строки данными
    for user_id, answers_dict in data.items():
        row = [user_id] + [answers_dict.get(q, "") for q in sorted_questions]
        ws.append(row)

    try:
        # Создаём Excel-файл в буфере памяти
        excel_buffer = io.BytesIO()
        wb.save(excel_buffer)
        excel_buffer.seek(0)

        excel_file = types.BufferedInputFile(
            excel_buffer.getvalue(),
            filename=f"анкеты_{event.event_date.strftime('%Y-%m-%d')}_{event.name}.xlsx",
        )

        await callback.answer(
            f"🗃 Анкеты для мероприятия {event.event_date.strftime('%Y-%m-%d')} {event.name} были экспортированы в Excel."
        )
        await callback.message.edit_text("🗃 Файл Анкеты для мероприятия:")
        await callback.message.answer_document(excel_file, caption="📄 Анкеты (Excel)")

    except Exception as e:
        logger.exception(f"Ошибка во время экспорта ответов мероприятия {event_id}: {e}")
        await callback.message.answer("Произошла ошибка при экспорте ответов.")
    finally:
        await state.clear()



# endregion
# ---------------------------------------------------------


# ---------------------------------------------------------
# region ViewRegistrations event
# ---------------------------------------------------------
@router.callback_query(F.data == "command_view_registrations")
async def view_registrations(callback: types.CallbackQuery, state: FSMContext):
    # Отвечаем на колбэк, чтобы убрать индикатор загрузки с кнопки
    await callback.answer()

    logger.info(
        f"Админ {callback.from_user.id} запросил просмотр регистраций мероприятий."
    )

    async with get_db() as session:
        events = await get_cached_active_events(session)

        if events:
            await callback.message.answer(
                "Выберите мероприятие:",
                reply_markup=get_events_kb(events)
            )

            await state.set_state(ViewRegistrations.event)

            logger.info(
                f"Отправлен список мероприятий админу {callback.from_user.id} для просмотра регистраций."
            )
        else:
            await callback.message.answer("Нет активных мероприятий.")



@router.callback_query(ViewRegistrations.event, lambda c: c.data.startswith("event_"))
async def show_registrations(callback: types.CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[1])
    await callback.answer(
        f"Админ {callback.from_user.id} выбрал мероприятие {event_id}"
    )
    async with get_db() as session:
        registrations = await Registration.get_registrations_info(session, event_id)
        event = await get_cached_event_by_id(
            session, event_id
        )  # получаем данные мероприятия

    event_date_str = event.event_date.strftime("%d.%m.%Y %H:%M")

    if registrations:
        users_list = "\n".join(
            [f"👤 {reg.first_name} {reg.last_name}" for reg in registrations]
        )
        await callback.message.edit_text(
            f"📅 <b>Мероприятие:</b> {event.name}\n\n🗓 <b>Дата проведения:</b> {event_date_str}\n\n"
            f"<b>Зарегистрированные пользователи:</b>\n{users_list}",
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            f"📅 <b>Мероприятие:</b> {event.name}\n\n🗓 <b>Дата проведения:</b> {event_date_str}\n\n"
            "На это мероприятие пока никто не зарегистрировался.",
            parse_mode="HTML",
        )

    await state.clear()


# endregion
# ---------------------------------------------------------


# ---------------------------------------------------------
# region AddAdmin(StatesGroup)
# ---------------------------------------------------------
@router.callback_query(F.data == "command_add_admin")
async def add_admin(callback: types.CallbackQuery, state: FSMContext):
    # Отвечаем на колбэк, чтобы убрать индикатор загрузки с кнопки
    await callback.answer()

    logger.info(f"Админ {callback.from_user.id} начал добавление нового администратора.")

    await callback.message.answer("Введите ID пользователя для назначения администратором:")

    await state.set_state(AddAdmin.user_id)



@router.message(AddAdmin.user_id)
async def process_admin_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text)
        await state.update_data(user_id=user_id)
        await message.answer("Введите пароль для нового администратора:")
        await state.set_state(AddAdmin.password)
        logger.info(f"Админ {message.from_user.id} указал ID нового админа: {user_id}.")
    except ValueError:
        await message.answer("Неверный формат ID.")
        logger.error(
            f"Админ {message.from_user.id} ввел неверный формат ID: {message.text}"
        )


@router.message(AddAdmin.password)
async def process_admin_password(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        async with get_db() as session:
            await User.add_admin(session, data["user_id"], message.text)
    except Exception as e:
        logger.exception(
            f"Ошибка добавления администратора {data['user_id']} пользователем {message.from_user.id}: {e}"
        )
        await message.answer("Ошибка добавления администратора.")
    else:
        await message.answer("Администратор успешно добавлен!")
        logger.info(
            f"Администратор {data['user_id']} успешно добавлен пользователем {message.from_user.id}."
        )
        await state.clear()


# endregion
# ---------------------------------------------------------


# ---------------------------------------------------------
# region ChangePassword(StatesGroup)
# ---------------------------------------------------------
@router.callback_query(F.data == "command_change_password")
async def change_password(callback: types.CallbackQuery, state: FSMContext):
    # Отвечаем на колбэк, чтобы убрать индикатор загрузки с кнопки
    await callback.answer()

    logger.info(f"Админ {callback.from_user.id} инициировал смену пароля.")

    await callback.message.answer("Введите текущий пароль:")

    await state.set_state(ChangePassword.old_password)


@router.message(ChangePassword.old_password)
async def process_old_password(message: Message, state: FSMContext):
    async with get_db() as session:
        user = await session.get(User, message.from_user.id)
        if user and user.verify_password(message.text):
            await state.update_data(old_password=message.text)
            await message.answer("Введите новый пароль:")
            await state.set_state(ChangePassword.new_password)
        else:
            await message.answer("Неверный пароль!")
            await state.clear()


@router.message(ChangePassword.new_password)
async def process_new_password(message: Message, state: FSMContext):
    async with get_db() as session:
        await User.update_admin_password(session, message.from_user.id, message.text)
    await message.answer("Пароль успешно изменен!")
    await state.clear()


# endregion
# ---------------------------------------------------------


# ---------------------------------------------------------
# region CancelEvent(StatesGroup)
# ---------------------------------------------------------
@router.callback_query(F.data == "command_cancel_event")
async def cancel_event(callback: types.CallbackQuery, state: FSMContext):
    # Отвечаем на колбэк, чтобы убрать индикатор загрузки с кнопки
    await callback.answer()

    logger.info(f"Админ {callback.from_user.id} начал процесс отмены мероприятия.")

    async with get_db() as session:
        events = await get_cached_active_events(session)

        if events:
            await callback.message.answer(
                "Выберите мероприятие для отмены:",
                reply_markup=get_events_kb(events)
            )

            await state.set_state(CancelEvent.event)

            logger.info(
                f"Отправлен список мероприятий админу {callback.from_user.id} для отмены."
            )
        else:
            await callback.message.answer("Нет активных мероприятий.")




@router.callback_query(CancelEvent.event, lambda c: c.data.startswith("event_"))
async def select_event_to_cancel(callback: types.CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[1])
    await callback.answer(
        f"Админ {callback.from_user.id} выбрал мероприятие {event_id}"
    )
    await state.update_data(event_id=event_id)
    await callback.message.edit_text(
        "Вы уверены, что хотите отменить мероприятие?",
        reply_markup=get_cancel_confirmation_kb(event_id),
    )
    await state.set_state(CancelEvent.confirmation)


@router.callback_query(CancelEvent.confirmation)
async def confirm_cancellation(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    if callback.data.startswith("cancel_confirm_"):
        event_id = int(callback.data.split("_")[2])
        await callback.answer(
            f"Админ {callback.from_user.id} отменил мероприятие {event_id}"
        )
        async with get_db() as session:
            # Получаем список пользователей перед удалением
            registrations = await Registration.get_registrations_info(session, event_id)
            users = [reg.user_id for reg in registrations]

            # Получаем информацию о мероприятии (нужно для уведомления админов)
            event = await get_cached_event_by_id(session, event_id)

            # Уведомляем администраторов с помощью функции notify_admins
            await notify_admins(bot, event)

            # Удаляем мероприятие
            success = await Event.cancel_event(session, event_id)
            # Очищаем кэш для этого мероприятия
            clear_event_from_cache(event_id)
            """Мероприятие: Тест

Дата: 23.05.2025

⚠️ Обратите, пожалуйста, внимание, что это событие было отменено. Актуальную информацию об этом и других мероприятиях вы сможете получить в нашем боте. 
На связи ⚠️"""
            if success:
                await callback.message.edit_text("Мероприятие успешно отменено!")
                # Отправляем уведомления зарегистрированным пользователям
                for user_id in users:
                    try:
                        await bot.send_message(
                            user_id,
                            f"<b>Мероприятие:</b> {event.name} ❌\n\n"
                            f"<b>Дата:</b> {event.event_date.strftime('%d.%m.%Y')}\n\n"
                            f"⚠️ <b>Обратите, пожалуйста, внимание, что это событие было отменено. Актуальную информацию об этом и других мероприятиях вы сможете получить в нашем боте.\nНа связи</b> ⚠️\n",
                            parse_mode="HTML",
                        )
                    except Exception as e:
                        logger.exception(
                            f"Ошибка отправки уведомления об отмене мероприятия пользователю {user_id}: {e}"
                        )

            else:
                await callback.message.answer("Ошибка при отмене мероприятия.")
    else:
        await callback.answer("Отмена мероприятия отклонена.")
        await callback.message.edit_text("Отмена мероприятия отклонена.")

    await state.clear()


# endregion
# ---------------------------------------------------------


# ---------------------------------------------------------
# region BroadcastMessage(StatesGroup)
# ---------------------------------------------------------
@router.callback_query(F.data == "command_broadcast")
async def broadcast(callback: types.CallbackQuery, state: FSMContext):
    # Отвечаем на колбэк, чтобы убрать индикатор загрузки с кнопки
    await callback.answer()

    await callback.message.answer(
        "Отправьте: "
        "\n - текст,"
        "\n - фото,"
        "\n - голосовое сообщение,"
        "\n - кружочек"
        "\nили видео для рассылки всем пользователям"
    )

    await state.set_state(BroadcastMessage.message)



# Обработчик ввода сообщения
@router.message(BroadcastMessage.message)
async def process_broadcast_message(message: Message, state: FSMContext):
    msg_data = {}

    if message.photo:
        msg_data["photo"] = message.photo[-1].file_id
        msg_data["caption"] = message.html_text or ""
        msg_data["type"] = "photo"
    elif message.voice:
        msg_data["voice"] = message.voice.file_id
        msg_data["caption"] = message.html_text or ""
        msg_data["type"] = "voice"
    elif message.video_note:
        msg_data["video_note"] = message.video_note.file_id
        msg_data["caption"] = ""  # кружочки не поддерживают подписи
        msg_data["type"] = "video_note"
    elif message.video:
        msg_data["video"] = message.video.file_id
        msg_data["caption"] = message.html_text or ""
        msg_data["type"] = "video"
    elif message.text:
        msg_data["text"] = message.html_text
        msg_data["type"] = "text"
    else:
        await message.answer(
            "❌ Этот тип сообщения не поддерживается."
            "\nОтправьте текст, фото, голосовое сообщение, кружочек или видео."
        )
        return

    await state.update_data(msg_data=msg_data)

    await message.answer(
        "Подтвердите рассылку:", reply_markup=get_broadcast_confirmation_kb()
    )
    await state.set_state(BroadcastMessage.confirmation)



@router.callback_query(BroadcastMessage.confirmation)
async def confirm_broadcast(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    if callback.data != "broadcast_confirm":
        await callback.answer("❌ Отмена рассылки...")
        await callback.message.answer("Рассылка отменена")
        logger.info(f"Рассылка отменена админом {callback.from_user.id}")
        await state.clear()
        return

    await callback.answer("✅ Подтверждено, сообщение добавлено в очередь рассылки...")
    data = await state.get_data()
    msg_data = data["msg_data"]

    logger.info(f"Админ {callback.from_user.id} добавил в очередь рассылку типа '{msg_data['type']}'")

    async with get_db() as session:
        # Подготовка данных для сохранения в БД
        if msg_data["type"] == "text":
            await BroadcastQueue.add_to_queue(
                session,
                text=msg_data["text"],
                media_type="text"
            )
        elif msg_data["type"] == "photo":
            await BroadcastQueue.add_to_queue(
                session,
                text=msg_data["caption"],
                media_id=msg_data["photo"],
                media_type="photo"
            )
        elif msg_data["type"] == "voice":
            await BroadcastQueue.add_to_queue(
                session,
                text=msg_data["caption"],
                media_id=msg_data["voice"],
                media_type="voice"
            )
        elif msg_data["type"] == "video_note":
            await BroadcastQueue.add_to_queue(
                session,
                media_id=msg_data["video_note"],
                media_type="video_note"
            )
        elif msg_data["type"] == "video":
            await BroadcastQueue.add_to_queue(
                session,
                text=msg_data["caption"],
                media_id=msg_data["video"],
                media_type="video"
            )

    await callback.message.answer(
        "Сообщение успешно добавлено в очередь рассылки. "
        "Оно будет отправлено пользователям в ближайшее время."
    )

    await state.clear()
# endregion
# ---------------------------------------------------------


# ---------------------------------------------------------
# region SetWelcomeVideo(StatesGroup)
# ---------------------------------------------------------
@router.callback_query(F.data == "command_set_welcome_video")
async def set_welcome_video(callback: types.CallbackQuery, state: FSMContext):
    # Отвечаем на колбэк, чтобы убрать индикатор загрузки с кнопки
    await callback.answer()

    logger.info(
        f"Админ {callback.from_user.id} начал процесс установки приветственного видео."
    )

    async with get_db() as session:
        events = await get_cached_active_events(session)

        await callback.message.answer(
            "Выберите мероприятие:",
            reply_markup=get_events_kb(events)
        )

        await state.set_state(SetWelcomeVideo.SELECT_EVENT)


@router.callback_query(SetWelcomeVideo.SELECT_EVENT, lambda c: c.data.startswith("event_"))
async def select_event_for_video(callback: types.CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[1])
    await callback.answer(f"Выбрано мероприятие {event_id}")
    async with get_db() as session:
        event = await session.get(Event, event_id)
    await callback.message.delete()
    if event and event.welcome_video_id:
        await callback.message.answer_video(
            video=event.welcome_video_id,
            caption=f"📹 Текущее ознакомительное видео для мероприятия <b>«{event.name}»</b>\n\n"
            "⬇️ Отправьте новое видео, чтобы обновить или используйте /cancel для отмены. ⬇️",
            parse_mode="HTML",
        )
    else:
        await callback.message.answer(
            "ℹ️ Для данного мероприятия пока нет установленного ознакомительного видео.\n\n"
            "⬇️ Отправьте новое приветственное видео или используйте /cancel для отмены. ⬇️"
        )


    await state.update_data(event_id=event_id)
    await state.set_state(SetWelcomeVideo.GET_VIDEO)


@router.message(Command("cancel"))
async def cancel_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()

    if current_state is None:
        await message.answer("⚠️ В данный момент нет активного действия для отмены.")
        return
    await message.delete()
    await state.clear()
    await message.answer("✅ Действие успешно отменено.")


@router.message(SetWelcomeVideo.GET_VIDEO, F.video | F.animation | F.video_note)
async def save_media(message: Message, state: FSMContext):
    media_id = None
    if message.video:
        media_id = message.video.file_id
    elif message.animation:
        media_id = message.animation.file_id
    elif message.video_note:
        media_id = message.video_note.file_id

    if not media_id:
        await message.answer("Отправьте видео, GIF или кружочек.")
        return

    data = await state.get_data()

    async with get_db() as session:
        success = await Event.set_welcome_video(session, data["event_id"], media_id)
        # Очищаем кэш для этого мероприятия
        clear_event_from_cache(data["event_id"])

    await message.delete()
    if success:
        await message.answer("✅ Медиа успешно обновлено!")
    else:
        await message.answer("⚠️ Ошибка обновления медиа.")

    await state.clear()


# endregion
# ---------------------------------------------------------
