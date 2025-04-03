import asyncio

from aiogram import types, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select

from src.config.logger_config import logger
from src.database.database import get_db
from src.database.models import User, Event, Registration, Answer, Question, SystemSetting
from src.database.models import (
    get_cached_event_by_id,
    get_cached_active_events,
    get_cached_questions,
)
from src.keyboards.keyboards import (
    get_registration_confirmation_kb,
    active_events_kb,
    digits_keyboard,
    events_keyboard,
    admin_keyboard,
    commands_keyboard,
)
from src.states.states import RegistrationForm

router = Router()


# Функции для получения настроек
async def get_video_file_id():
    async with get_db() as session:
        return await SystemSetting.get_setting_cached(session, "VIDEO_FILE_ID", "")


async def get_admin_commands_text():
    async with get_db() as session:
        return await SystemSetting.get_setting_cached(
            session, "ADMIN_COMMANDS_TEXT", ""
        )


async def get_start_message():
    async with get_db() as session:
        return await SystemSetting.get_setting_cached(session, "START_MESSAGE", "")


async def get_welcome_message():
    async with get_db() as session:
        return await SystemSetting.get_setting_cached(session, "WELCOME_MESSAGE", "")


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
# region Command("start")
# ---------------------------------------------------------
@router.message(CommandStart())
async def start(message: Message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    await async_log_user_action(user_id, "запустил команду /start", his=False)

    async with get_db() as session:
        # Объединение операций в одну транзакцию
        user = await User.add_user(
            session,
            user_id,
            message.from_user.first_name,
            message.from_user.last_name,
        )

        is_admin = user.is_admin  # Используем данные из полученного объекта
        await async_log_user_action(
            user_id,
            f"проверка админ-прав: {'администратор' if is_admin else 'обычный пользователь'}.",
            his=False,
        )

    text = f"👋 Привет, <b>{user_name}</b>!\n\n"
    if is_admin:
        text += "Ваш статус - администратор, вам доступны команды:\n\n"
        text += await get_admin_commands_text()
        # Клавиатура для админа
        await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard)
        await async_log_user_action(
            user_id,
            "показано приветственное сообщение со списком админ-команд.",
            his=True,
        )

    else:
        # Получаем ID видео из базы вместо использования константы
        video_id = await get_video_file_id()

        await message.answer_video(
            video=video_id,
            caption="",
        )

        text += await get_start_message()
        await message.answer(text, parse_mode="HTML", reply_markup=events_keyboard)
        welcome_message = await get_welcome_message()
        await message.answer(
            welcome_message, parse_mode="HTML", reply_markup=digits_keyboard
        )

        await async_log_user_action(
            user_id, "показано стандартное приветственное сообщение.", his=True
        )


@router.message(Command("give_my_id"))
async def give_my_id(message: Message):
    user_id = message.from_user.id
    await async_log_user_action(
        user_id, f"вызвал команду /give_my_id. Запрошен ID пользователя.", his=False
    )

    await message.answer(f"Ваш ID: {user_id}")


@router.message(F.text.lower() == "команды")
async def send_commands_inline(message: types.Message):
    await message.answer("Выберите команду:", reply_markup=commands_keyboard)


@router.callback_query(F.data.startswith("digit_"))
async def process_digit(callback: CallbackQuery):
    digit = callback.data.split("_")[-1]
    user_name = callback.from_user.first_name
    user_id = callback.from_user.id
    await async_log_user_action(user_id, f"нажал кнопку {digit}", his=False)

    # Отвечаем пользователю благодарностью за выбор
    await callback.answer(f"Спасибо что поделились, {user_name}!", show_alert=True)

    # Теперь удаляем предыдущее сообщение с клавиатурой
    await callback.message.delete()

    # Продолжаем работу бота
    await offer_active_events(callback.message)


@router.message(F.text == "Мероприятия")
async def handle_events_button(message: types.Message):
    await message.delete()
    await async_log_user_action(
        message.from_user.id, f"нажал кнопку: {message.text}", his=False
    )

    # Вызываем нужную функцию предложений мероприятий
    await offer_active_events(message)


async def offer_active_events(message: Message):
    """Функция предложит пользователю доступные мероприятия"""
    user_id = (message.from_user.id,)
    await async_log_user_action(
        user_id[0], "запросил список доступных мероприятий.", his=False
    )
    async with get_db() as session:
        events = await get_cached_active_events(session)

        if events:
            await message.answer(
                "Доступные мероприятия для регистрации:",
                reply_markup=active_events_kb(events),
            )

            await async_log_user_action(
                user_id[0],
                f"получил мероприятия для регистрации (всего: {len(events)}).",
                his=False,
            )
        else:
            await message.answer("В настоящее время нет активных мероприятий.")

            await async_log_user_action(
                user_id[0],
                "получил сообщение об отсутствии активных мероприятий.",
                his=False,
            )


# endregion
# ---------------------------------------------------------


# ---------------------------------------------------------
# region RegistrationForm(StatesGroup)
# ---------------------------------------------------------
async def ask_question(message: Message, state: FSMContext, questions, question_index):
    """Функция задает вопрос или завершает регистрацию, если вопросы закончились"""
    user_id = message.from_user.id
    if question_index < len(questions):
        await state.update_data(current_question_index=question_index)
        question_text = questions[question_index].question_text
        await message.answer(question_text)

        await async_log_user_action(
            user_id,
            f"отправлен вопрос: '{question_text}' (индекс {question_index})",
            his=True,
        )
        await state.set_state(RegistrationForm.DYNAMIC_QUESTION)
    else:
        # вопросы закончились, финализируем регистрацию
        data = await state.get_data()
        event_id = data["event_id"]

        await async_log_user_action(
            user_id,
            "завершил ответы на вопросы, начинаем финализацию регистрации",
            his=False,
        )
        async with get_db() as session:
            reg = Registration(user_id=user_id, event_id=event_id)
            session.add(reg)
            # await session.commit()

            await async_log_user_action(
                user_id, f"сохранена Регистрация (Event ID: {event_id})", his=True
            )
            # Сохраняем ответы в БД
            answers = [
                Answer(
                    registration_user_id=reg.user_id,
                    registration_event_id=reg.event_id,
                    question_id=data["questions"][idx],
                    answer_text=answer_text,
                )
                for idx, answer_text in enumerate(data["answers"])
            ]
            session.add_all(answers)
            await session.commit()

            await async_log_user_action(
                user_id, f"добавлены Ответы в БД: {len(answers)}", his=True
            )
            video_id = await Event.get_welcome_video(session, data["event_id"])

        if video_id:
            await message.answer("Посмотрите вводное видео:")
            await message.bot.send_video(
                chat_id=user_id,
                video=video_id,
                caption="Спасибо за регистрацию!",
            )

            await async_log_user_action(
                user_id, "отправлено приветственное видео после регистрации", his=True
            )
        else:
            await message.answer("Спасибо за регистрацию!")

            await async_log_user_action(
                user_id,
                "отправлено уведомление о завершении регистрации (без видео)",
                his=True,
            )
        await message.answer("📌 Регистрация завершена!")
        await state.clear()


# старт динамической анкеты:
@router.callback_query(lambda c: c.data.startswith("register_"))
async def event_description(callback: types.CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id

    await async_log_user_action(
        user_id, f"запросил описание мероприятия с ID {event_id}", his=False
    )
    async with get_db() as session:
        event = await get_cached_event_by_id(session, event_id)
        if not event:
            logger.warning(
                f"Мероприятие с ID {event_id} не найдено при запросе от пользователя {callback.from_user.id}"
            )
            await callback.answer("❌ Мероприятие не найдено.", show_alert=True)
            return

        await callback.answer(f"Описание мероприятия ID: {event_id}")

        description = event.description
        date = event.event_date.strftime("%d.%m.%Y в %H:%M")

        text = (
            f"📌 <b>{event.name}</b>\n\n"
            f"📅 <b>Дата и время:</b> {date}\n\n"
            f"📝 <b>Описание:</b> <i>{description}</i>\n\n"
            "<b>Хотите зарегистрироваться на это мероприятие?</b>"
        )

        await callback.message.edit_text(
            text,
            reply_markup=get_registration_confirmation_kb(event_id),
            parse_mode="HTML",
        )

        await async_log_user_action(
            user_id, f"показано описание мероприятия с ID {event_id}", his=True
        )


@router.callback_query(lambda c: c.data == "confirm_no")
async def confirm_no(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await async_log_user_action(
        user_id, f"отменил регистрацию на мероприятие", his=False
    )

    async with get_db() as session:
        events = await get_cached_active_events(session)

        if events:
            await callback.message.edit_text(
                "Доступные мероприятия для регистрации:",
                reply_markup=active_events_kb(events),
            )
            await callback.answer("Выберите другое мероприятие.")
            await async_log_user_action(
                user_id, f"снова показан список мероприятий.", his=True
            )
        else:
            await callback.message.edit_text(
                "В настоящее время нет активных мероприятий."
            )
            await callback.answer("Активных мероприятий нет.")
            await async_log_user_action(
                user_id, f"сообщено о том, что мероприятий нет.", his=True
            )


@router.callback_query(lambda c: c.data.startswith("confirm_yes_"))
async def confirm_yes(callback: types.CallbackQuery, state: FSMContext):
    event_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    await async_log_user_action(
        user_id, f"подтвердил участие в мероприятии с ID {event_id}", his=False
    )

    await callback.message.edit_text("Пожалуйста, ответьте на пару вопросов:")

    await callback.answer(
        f"Вы выбрали мероприятие ID: «{event_id}».\nПожалуйста, ответьте на несколько вопросов."
    )

    async with get_db() as session:
        existing_registration = await session.scalar(
            select(Registration).where(
                Registration.user_id == user_id, Registration.event_id == event_id
            )
        )
        event = await get_cached_event_by_id(session, event_id)
        if existing_registration:

            await async_log_user_action(
                user_id,
                f"уже был ранее зарегистрирован на мероприятие «{event.name}» ID {event_id}",
                his=False,
            )

            await callback.message.edit_text(
                f"✅ Вы уже зарегистрированы на мероприятие:\n\n"
                f"«{event.name}»\n\n"
                f"📅 Дата: {event.event_date.strftime('%d.%m.%Y в %H:%M')}\n"
            )
            return

        questions = await Question.get_questions(session, event_id)

        # Проработка ситуации отсутствия вопросов
        if not questions:
            logger.warning(f"Отсутствуют вопросы анкеты для мероприятия ID {event_id}")

            # Создаем регистрацию пользователя сразу
            registration = Registration(event_id=event_id, user_id=user_id)
            session.add(registration)
            await session.commit()
            await async_log_user_action(
                user_id,
                f"успешно зарегистрирован на мероприятие ID {event_id} (без анкеты)",
                his=False,
            )

            # Замена сообщения подтверждением регистрации
            await callback.message.edit_text(
                f"✅ Вы успешно зарегистрированы на мероприятие:\n\n"
                f"«{event.name}»\n\n"
                f"📅 Дата: {event.event_date.strftime('%d.%m.%Y в %H:%M')}\n"
            )
            await callback.answer("Вы успешно зарегистрированы!")
            return

        # Если вопросы есть — начинаем анкету
        await state.update_data(
            event_id=event_id, questions=[q.id for q in questions], answers=[]
        )
        await async_log_user_action(
            user_id,
            f"направлено начало анкеты из {len(questions)} вопросов для мероприятия ID {event_id}",
            his=True,
        )

        await callback.answer(f"Анкета состоит из {len(questions)} вопросов")
        await ask_question(callback.message, state, questions, 0)


# универсальный обработчик ответов на вопросы независимо от их количества:
@router.message(RegistrationForm.DYNAMIC_QUESTION)
async def handle_dynamic_question(message: Message, state: FSMContext):
    data = await state.get_data()
    current_index = data.get("current_question_index", 0)

    # добавляем текущий ответ в массив
    answers = data.get("answers", [])
    answers.append(message.text)
    await state.update_data(answers=answers)

    async with get_db() as session:
        questions = await get_cached_questions(session, data["event_id"])

    # переходим к следующему вопросу или завершаем регистрацию
    await ask_question(message, state, questions, current_index + 1)


# endregion
# ---------------------------------------------------------
