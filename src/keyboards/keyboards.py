from typing import List

from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.database.models import Event

admin_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Команды")]], resize_keyboard=True
)

events_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Мероприятия")]],
    resize_keyboard=True,
    one_time_keyboard=True,
)


def create_inline_kb(
    buttons: list[tuple[str, str]], adjust: int = 2
) -> InlineKeyboardMarkup:
    """
    Создаёт Inline-клавиатуру из списка кнопок.

    :param buttons: [(текст кнопки, callback-данные кнопки), ...]
    :param adjust: количество кнопок в строке
    :return: InlineKeyboardMarkup
    """
    builder = InlineKeyboardBuilder()
    for text, callback_data in buttons:
        builder.button(text=text, callback_data=callback_data)
    builder.adjust(adjust)
    return builder.as_markup()


commands_keyboard = create_inline_kb(
    [
        ("✅ Добавить Рассылку 📢", "command_broadcast"),
        ("✅ Добавить мероприятие 📅", "command_add_event"),
        ("🚫 Отменить мероприятие 📅", "command_cancel_event"),
        ("✏️ Редактировать вопросы ❓", "command_edit_questions"),
        ("🪄 Изменить видео 🎬", "command_set_welcome_video"),
        ("📤 Выгрузка ответов 📋", "command_export_answers"),
        ("👓 Просмотр списков 📜", "command_view_registrations"),
        ("✅ Назначить админом 🥋", "command_add_admin"),
        ("♻️ Сменить пароль админа 🔐", "command_change_password"),
        ("⚙️ Настройка контента 📼", "command_edit_settings"),
    ],
    adjust=1,
)

edit_setting_keyboard = create_inline_kb(
    [
        ("✏️ Видео приветствия 📽", "edit_setting_VIDEO_FILE_ID"),
        ("✏️ Стартовое сообщение 📃", "edit_setting_START_MESSAGE"),
        ("✏️ Текст команд админа 🛠", "edit_setting_ADMIN_COMMANDS_TEXT"),
    ],
    adjust=1,
)

digits_keyboard = create_inline_kb([(str(i), f"digit_{i}") for i in range(1, 4)])


def create_time_keyboard(
    start_hour: int = 8, end_hour: int = 22, buttons_per_row: int = 4
) -> InlineKeyboardMarkup:
    buttons = []
    # Создаем список кнопок для интервала времени
    for hour in range(start_hour, end_hour + 1):
        buttons.append((f"{hour:02}:00", f"time_{hour:02}:00"))
        buttons.append((f"{hour:02}:30", f"time_{hour:02}:30"))

    # Используем create_inline_kb для создания клавиатуры
    return create_inline_kb(buttons, buttons_per_row)


def active_events_kb(events: List[Event]):
    return create_inline_kb(
        [(event.name, f"register_{event.id}") for event in events], adjust=1
    )


def get_registration_kb(event_id):
    return create_inline_kb([("Зарегистрироваться", f"register_{event_id}")])


def get_events_kb(events):
    return create_inline_kb(
        [(event.name, f"event_{event.id}") for event in events], adjust=1
    )


def get_confirm_kb():
    return create_inline_kb([("✅ Подтвердить", "confirm"), ("❌ Отменить", "cancel")])


def get_cancel_confirmation_kb(event_id):
    return create_inline_kb(
        [
            ("✅ Подтвердить", f"cancel_confirm_{event_id}"),
            ("❌ Отмена", "cancel_reject"),
        ]
    )


def get_broadcast_confirmation_kb():
    return create_inline_kb(
        [
            ("✅ Отправить всем", "broadcast_confirm"),
            ("❌ Отменить", "broadcast_cancel"),
        ]
    )


def get_registration_confirmation_kb(event_id):
    return create_inline_kb(
        [
            ("✅ Да", f"confirm_yes_{event_id}"),
            ("❌ Нет", "confirm_no"),
        ]
    )


def create_question_keyboard(questions):
    return create_inline_kb(
        [(question.question_text, f"question_{question.id}") for question in questions],
        adjust=1,
    )
