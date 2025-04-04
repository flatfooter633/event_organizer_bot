from aiogram.fsm.state import StatesGroup, State


# ---------------------------------------------------------
# region StatesGroup
# ---------------------------------------------------------
class BroadcastMessage(StatesGroup):
    message = State()
    confirmation = State()


class RegistrationForm(StatesGroup):
    DYNAMIC_QUESTION = State()


class EditReminder(StatesGroup):
    event = State()
    type = State()
    text = State()


class SetWelcomeVideo(StatesGroup):
    SELECT_EVENT = State()
    GET_VIDEO = State()


class ViewRegistrations(StatesGroup):
    event = State()


class CancelEvent(StatesGroup):
    event = State()
    confirmation = State()


class AdminAuth(StatesGroup):
    password = State()


class AddAdmin(StatesGroup):
    user_id = State()
    password = State()


class ChangePassword(StatesGroup):
    old_password = State()
    new_password = State()


class AddEvent(StatesGroup):
    name = State()
    description = State()
    date = State()
    choosing_date = State()
    choosing_time = State()
    question = State()


class EditQuestions(StatesGroup):
    EVENT = State()
    QUESTION = State()
    TEXT = State()


class ExportAnswers(StatesGroup):
    event = State()


# Добавляем новое состояние для добавления вопросов к существующему мероприятию
class AddQuestionsToEvent(StatesGroup):
    question = State()  # Состояние для добавления вопросов


class AdminStates(StatesGroup):
    edit_setting = State()
    edit_video_setting = State()


# endregion
# ---------------------------------------------------------
