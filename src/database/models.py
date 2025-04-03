from datetime import datetime, UTC
from typing import Sequence, Optional

from cachetools import cached
from passlib.context import CryptContext
from sqlalchemy import ForeignKey, String, DateTime, Text, Boolean
from sqlalchemy import ForeignKeyConstraint, and_
from sqlalchemy import select, exists
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload, joinedload

from src.config.config import Base
from src.config.logger_config import logger
from src.utils.cache import events_cache, system_cache


@cached(cache=events_cache)
async def get_cached_event_by_id(session, event_id):
    return await Event.get_event_by_id(session, event_id)


@cached(cache=events_cache)
async def get_cached_active_events(session):
    return await Event.get_active_events(session)


@cached(cache=events_cache)
async def get_cached_questions(session, event_id):
    return await Question.get_questions(session, event_id)


@cached(cache=events_cache)
async def check_admin_cached(session, user_id):
    return await User.check_admin(session, user_id)


def clear_event_from_cache(event_id):
    """Очищает все записи в кеше, связанные с указанным event_id"""
    keys_to_remove = []
    for key in list(events_cache.keys()):
        # Проверяем, содержит ли ключ наш event_id
        if isinstance(key, tuple) and any(str(event_id) in str(k) for k in key):
            keys_to_remove.append(key)

    # Удаляем найденные ключи из кеша
    for key in keys_to_remove:
        if key in events_cache:
            del events_cache[key]


def clear_all_cache():
    """Очищает весь кэш событий"""
    events_cache.clear()


pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,  # Можно настроить количество раундов
)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    @classmethod
    async def get_setting(cls, session: AsyncSession, key: str, default=None):
        """Получить значение настройки по ключу"""
        stmt = select(cls).where(cls.key == key)
        result = await session.execute(stmt)
        setting = result.scalars().first()
        return setting.value if setting else default

    @classmethod
    async def set_setting(
        cls,
        session: AsyncSession,
        key: str,
        value: str,
        description: Optional[str] = None,
    ):
        """Установить значение настройки"""
        stmt = select(cls).where(cls.key == key)
        result = await session.execute(stmt)
        setting = result.scalars().first()

        if setting:
            setting.value = value
            if description:
                setting.description = description
        else:
            new_setting = cls(key=key, value=value, description=description)
            session.add(new_setting)

        await session.commit()
        # Обновляем кэш, если настройка кэшируется
        await cls.clear_setting_cache(key)
        return True

    @classmethod
    async def get_setting_cached(cls, session: AsyncSession, key: str, default=None):
        """Получить значение настройки из кэша или из базы"""
        cache_key = f"setting:{key}"
        cached_value = system_cache.get(cache_key)

        if cached_value is not None:
            return cached_value

        value = await cls.get_setting(session, key, default)
        if value is not None:
            # Используем словарное присваивание вместо метода set
            system_cache[cache_key] = value
        return value

    @classmethod
    async def clear_setting_cache(cls, key: str):
        """Очистить кэш для конкретной настройки"""
        cache_key = f"setting:{key}"
        # Используем del вместо метода delete
        if cache_key in system_cache:
            del system_cache[cache_key]


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=True)
    registrations: Mapped[list["Registration"]] = relationship(back_populates="user")

    def verify_password(self, password: str):
        """Проверяет, соответствует ли предоставленный пароль хешу пароля пользователя."""
        return pwd_context.verify(password, self.password_hash)

    @staticmethod
    def get_password_hash(password: str):
        """Создает хеш для заданного пароля."""
        return pwd_context.hash(password)

    @classmethod
    async def get_all_users(cls, session: AsyncSession):
        """Получает ID всех пользователей."""
        result = await session.execute(select(cls.user_id))
        return [row[0] for row in result.all()]

    @classmethod
    async def get_all_admins(cls, session):
        """Получает всех пользователей с правами администратора."""
        result = await session.execute(select(cls).filter(cls.is_admin == True))
        return result.scalars().all()

    @classmethod
    async def add_user(
        cls,
        session: AsyncSession,
        user_id: int,
        first_name: str,
        last_name: str,
        is_admin: bool = False,
    ):
        """Добавляет нового пользователя или возвращает существующего."""
        try:
            user = await session.get(cls, user_id)
            if not user:
                user = cls(
                    user_id=user_id,
                    first_name=first_name,
                    last_name=last_name,
                    is_admin=is_admin,
                )
                session.add(user)
                await session.commit()
                logger.info(f"Добавлен новый пользователь (user_id={user_id})")
            else:
                logger.info(f"Пользователь уже существует (user_id={user_id})")
            # Возвращаем пользователя в любом случае
            return user

        except SQLAlchemyError as e:
            await session.rollback()
            logger.exception(
                f"Ошибка при добавлении пользователя (user_id={user_id}) {str(e)}"
            )
            return None  # Возвращаем None при ошибке

    @classmethod
    async def add_admin(cls, session: AsyncSession, user_id: int, password: str):
        """Добавляет нового администратора или обновляет существующего пользователя до администратора."""
        try:
            user = await session.get(cls, user_id)
            if user:
                user.is_admin = True
                user.password_hash = cls.get_password_hash(password)
                action = "Обновлены права пользователя до администратора"
            else:
                user = cls(
                    user_id=user_id,
                    is_admin=True,
                    password_hash=cls.get_password_hash(password),
                )
                session.add(user)
                action = "Добавлен новый администратор"
            await session.commit()
            logger.info(f"{action} (user_id={user_id})")
            return True
        except SQLAlchemyError as e:
            await session.rollback()
            logger.exception(
                f"Ошибка при добавлении или обновлении администратора (user_id={user_id}): {str(e)}"
            )
            return False

    @classmethod
    async def check_admin(cls, session: AsyncSession, user_id: int):
        """Проверяет, является ли пользователь администратором."""
        user = await session.get(cls, user_id)
        is_admin = user.is_admin if user else False
        logger.info(
            f"Проверка прав администратора (user_id={user_id}, is_admin={is_admin})"
        )
        return is_admin

    @classmethod
    async def update_admin_password(
        cls, session: AsyncSession, user_id: int, new_password: str
    ):
        """Обновляет пароль администратора."""
        user = await session.get(cls, user_id)
        if user and user.is_admin:
            try:
                user.password_hash = cls.get_password_hash(new_password)
                await session.commit()
                logger.info(f"Пароль администратора обновлен (user_id={user_id})")
                return True
            except SQLAlchemyError as e:
                await session.rollback()
                logger.exception(
                    f"Ошибка при обновлении пароля администратора (user_id={user_id}) {str(e)}"
                )
        else:
            logger.warning(
                f"Попытка обновления пароля несуществующего администратора (user_id={user_id})"
            )
        return False

    @classmethod
    async def get_all_user_ids(cls, session: AsyncSession) -> list[int] | Sequence[int]:
        """Получает ID всех пользователей."""
        try:
            result = await session.execute(select(cls.user_id))
            user_ids = result.scalars().all()
            logger.debug(f"Получены ID всех пользователей, всего: {len(user_ids)}")
            return user_ids
        except SQLAlchemyError as e:
            logger.exception(f"Ошибка при получении ID всех пользователей: {str(e)}")
            return []


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    event_date: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="active")
    reminder_week: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_3days: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_day: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_hours: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_hour: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_video_id: Mapped[str] = mapped_column(String(255), nullable=True)
    registrations: Mapped[list["Registration"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    questions: Mapped[list["Question"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )

    @classmethod
    async def add_event(
        cls, session: AsyncSession, name: str, description: str, event_date: datetime
    ):
        """Добавляет новое мероприятие."""
        try:
            event = cls(name=name, description=description, event_date=event_date)
            session.add(event)
            await session.commit()
            logger.info(f"Добавлено мероприятие '{name}' на дату {event_date}")
            return event
        except SQLAlchemyError as e:
            await session.rollback()
            logger.exception(f"Ошибка добавления мероприятия '{name}': {str(e)}")

    @classmethod
    async def get_events(cls, session: AsyncSession):
        """Получает все мероприятия."""
        try:
            result = await session.execute(select(cls))
            events = result.scalars().all()
            logger.debug(f"Получены мероприятия, всего записей: {len(events)}")
            return events
        except SQLAlchemyError as e:
            logger.exception(f"Ошибка получения списка мероприятий: {str(e)}")
            return []

    @classmethod
    async def get_active_events(cls, session: AsyncSession):
        """Получает все активные мероприятия."""
        result = await session.execute(select(cls).where(cls.status == "active"))
        return result.scalars().all()

    @classmethod
    async def get_active_events_with_questions_and_answers(cls, session: AsyncSession):
        """Возвращает активные мероприятия, у которых заданы вопросы и есть хотя бы один ответ."""

        # Создаём подзапросы для проверки наличия вопросов и ответов.

        # Подзапрос для проверки наличия вопросов
        question_exists_subquery = exists(
            select(Question.id).where(Question.event_id == cls.id)
        )

        # Подзапрос для проверки наличия ответов через Registration и Answer
        answer_exists_subquery = exists(
            select(Answer.id).where(Answer.registration_event_id == cls.id)
        )

        result = await session.execute(
            select(cls)
            .options(joinedload(cls.questions))
            .where(
                cls.status == "active", question_exists_subquery, answer_exists_subquery
            )
        )

        return result.unique().scalars().all()

    @classmethod
    async def get_event_by_id(cls, session: AsyncSession, event_id: int):
        """Получает мероприятие по его ID."""
        try:
            result = await session.execute(select(cls).where(cls.id == event_id))
            event = result.scalar_one_or_none()
            if event:
                logger.debug(f"Получено мероприятие (event_id={event_id})")
            else:
                logger.warning(f"Мероприятие не найдено (event_id={event_id})")
            return event
        except SQLAlchemyError as e:
            logger.exception(
                f"Ошибка при получении мероприятия (event_id={event_id}): {str(e)}"
            )
            return None

    @classmethod
    async def get_event_with_questions(cls, session: AsyncSession, event_id: int):
        """Получение мероприятия с его вопросами за один запрос"""
        stmt = (
            select(Event)
            .options(selectinload(Event.questions))
            .filter(Event.id == event_id)
        )
        return await session.scalar(stmt)

    @classmethod
    async def cancel_event(cls, session: AsyncSession, event_id: int):
        """Отменяет мероприятие."""
        try:
            event = await cls.get_event_by_id(session, event_id)
            if event:
                await session.delete(event)
                await session.commit()
                logger.info(f"Мероприятие отменено (event_id={event_id})")
                return True
            else:
                logger.warning(
                    f"Попытка отмены несуществующего мероприятия (event_id={event_id})"
                )
        except SQLAlchemyError as e:
            await session.rollback()
            logger.exception(
                f"Ошибка при отмене мероприятия (event_id={event_id}): {str(e)}"
            )
        return False

    @classmethod
    async def set_welcome_video(
        cls, session: AsyncSession, event_id: int, video_id: str
    ):
        """Устанавливает приветственное видео для мероприятия."""
        try:
            event = await session.get(cls, event_id)
            if event:
                event.welcome_video_id = video_id
                await session.commit()
                logger.info(
                    f"Установлено приветственное видео для мероприятия (event_id={event_id}) video_id={video_id}"
                )
                return True
            logger.warning(
                f"Мероприятие для установки видео не найдено (event_id={event_id})"
            )
        except SQLAlchemyError as e:
            await session.rollback()
            logger.exception(
                f"Ошибка при установке приветственного видео (event_id={event_id}): {str(e)}"
            )
        return False

    @classmethod
    async def get_welcome_video(cls, session: AsyncSession, event_id: int):
        """Получает ID приветственного видео для мероприятия."""
        try:
            event = await session.get(cls, event_id)
            if event and event.welcome_video_id:
                logger.debug(
                    f"Получено приветственное видео для мероприятия (event_id={event_id})"
                )
                return event.welcome_video_id
            else:
                logger.warning(
                    f"Приветственное видео не найдено или отсутствует для мероприятия (event_id={event_id})"
                )
                return None
        except SQLAlchemyError as e:
            logger.exception(
                f"Ошибка при получении приветственного видео (event_id={event_id}): {str(e)}"
            )
            return None

    @classmethod
    async def update_reminder(
        cls, session: AsyncSession, event_id: int, reminder_type: str, text: str
    ):
        """Обновляет текст напоминания для мероприятия."""
        try:
            event = await cls.get_event_by_id(session, event_id)
            if event:
                setattr(event, f"reminder_{reminder_type}", text)
                await session.commit()
                logger.info(
                    f"Обновлено напоминание '{reminder_type}' для мероприятия (event_id={event_id})"
                )
                return True
            else:
                logger.warning(
                    f"Не найдено мероприятие для обновления напоминания (event_id={event_id})"
                )
        except SQLAlchemyError as e:
            await session.rollback()
            logger.exception(
                f"Ошибка при обновлении напоминания (event_id={event_id}, reminder_type={reminder_type}): {str(e)}"
            )
        return False


class Registration(Base):
    __tablename__ = "registrations"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), primary_key=True)
    registration_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    user: Mapped["User"] = relationship(back_populates="registrations")
    event: Mapped["Event"] = relationship(back_populates="registrations")
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="registration",
        cascade="all, delete-orphan",
        primaryjoin="and_(Registration.user_id == Answer.registration_user_id, "
        "Registration.event_id == Answer.registration_event_id)",
    )

    @classmethod
    async def get_registrations_info(cls, session: AsyncSession, event_id: int):
        """Получает информацию о регистрациях на мероприятие."""
        try:
            result = await session.execute(
                select(User.user_id, User.first_name, User.last_name)
                .join(cls, cls.user_id == User.user_id)
                .where(cls.event_id == event_id)
            )
            registrations = result.all()
            logger.debug(
                f"Получены регистрации на мероприятие (event_id={event_id}), найдено {len(registrations)}"
            )
            return registrations
        except SQLAlchemyError as e:
            logger.exception(
                f"Ошибка получения регистраций мероприятия (event_id={event_id}): {str(e)}"
            )
            return []

    @classmethod
    async def register_user(cls, session: AsyncSession, user_id: int, event_id: int):
        """Регистрирует пользователя на мероприятие."""
        try:
            registration = cls(user_id=user_id, event_id=event_id)
            session.add(registration)
            await session.commit()
            logger.info(
                f"Пользователь (user_id={user_id}) зарегистрирован на мероприятие (event_id={event_id})"
            )
            return True
        except SQLAlchemyError as e:
            await session.rollback()
            logger.exception(
                f"Ошибка регистрации пользователя (user_id={user_id}) на мероприятие (event_id={event_id}): {str(e)}"
            )
            return False

    @classmethod
    async def get_registered_users(cls, session: AsyncSession, event_id: int):
        """Получает список ID пользователей, зарегистрированных на мероприятие."""
        try:
            result = await session.execute(
                select(User.user_id).join(cls).where(cls.event_id == event_id)
            )
            users = [row[0] for row in result.all()]
            logger.debug(
                f"Получены зарегистрированные пользователи для мероприятия (event_id={event_id}), всего {len(users)}"
            )
            return users
        except SQLAlchemyError as e:
            logger.exception(
                f"Ошибка получения зарегистрированных пользователей (event_id={event_id}): {str(e)}"
            )
            return []


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    question_text: Mapped[str] = mapped_column(Text)
    order: Mapped[int] = mapped_column(default=1)

    event: Mapped["Event"] = relationship(back_populates="questions")

    @classmethod
    async def get_questions(cls, session: AsyncSession, event_id: int):
        """Получает все вопросы для мероприятия."""
        try:
            result = await session.execute(
                select(cls).where(cls.event_id == event_id).order_by(cls.order)
            )
            questions = result.scalars().all()
            logger.debug(
                f"Получены вопросы мероприятия (event_id={event_id}), вопросов: {len(questions)}"
            )
            return questions
        except SQLAlchemyError as e:
            logger.exception(
                f"Ошибка получения вопросов мероприятия (event_id={event_id}): {str(e)}"
            )
            return []

    @classmethod
    async def update_question(
        cls, session: AsyncSession, question_id: int, new_text: str
    ):
        """Обновляет текст вопроса."""
        question = await session.get(cls, question_id)
        if question:
            try:
                question.question_text = new_text
                await session.commit()
                logger.info(f"Обновлён текст вопроса (question_id={question_id})")
                return True
            except SQLAlchemyError as e:
                await session.rollback()
                logger.exception(
                    f"Ошибка при обновлении текста вопроса (question_id={question_id}): {str(e)}"
                )
        else:
            logger.warning(
                f"Попытка обновления несуществующего вопроса (question_id={question_id})"
            )
        return False


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    registration_user_id: Mapped[int] = mapped_column()
    registration_event_id: Mapped[int] = mapped_column()
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    answer_text: Mapped[str] = mapped_column(Text)

    registration: Mapped["Registration"] = relationship(
        back_populates="answers",
        primaryjoin="and_(Answer.registration_user_id == Registration.user_id, "
        "Answer.registration_event_id == Registration.event_id)",
    )
    question: Mapped["Question"] = relationship()

    __table_args__ = (
        ForeignKeyConstraint(
            ["registration_user_id", "registration_event_id"],
            ["registrations.user_id", "registrations.event_id"],
        ),
    )

    @classmethod
    async def get_answers_for_event(cls, session: AsyncSession, event_id: int):
        """Получает все ответы для мероприятия с информацией о пользователях и вопросах,
        сортируя вопросы по полю `order`."""
        try:
            result = await session.execute(
                select(User.user_id, Question.question_text, cls.answer_text)
                .join(Registration, Registration.user_id == User.user_id)
                .join(
                    cls,
                    and_(
                        cls.registration_user_id == Registration.user_id,
                        cls.registration_event_id == Registration.event_id,
                    ),
                )
                .join(Question, Question.id == cls.question_id)
                .where(Registration.event_id == event_id)
                .order_by(Question.order)  # Добавили сортировку вопросов
            )
            logger.debug(f"Получены ответы для мероприятия (event_id={event_id})")
            return result.all()
        except SQLAlchemyError as e:
            logger.exception(
                f"Ошибка получения ответов для мероприятия (event_id={event_id}): {str(e)}"
            )
            return []

    @classmethod
    async def get_answers_for_output(cls, session: AsyncSession, event_id: int):
        """Получает ответы для мероприятия в формате, удобном для вывода."""
        try:
            result = await session.execute(
                select(User.user_id, Question.id, cls.answer_text)
                .join(Registration, Registration.user_id == User.user_id)
                .join(
                    cls,
                    and_(
                        cls.registration_user_id == Registration.user_id,
                        cls.registration_event_id == Registration.event_id,
                    ),
                )
                .join(Question, Question.id == cls.question_id)
                .where(Registration.event_id == event_id)
            )
            logger.debug(f"Получены ответы для мероприятия (event_id={event_id})")
            return result.all()
        except SQLAlchemyError as e:
            logger.exception(
                f"Ошибка получения ответов для мероприятия (event_id={event_id}): {str(e)}"
            )
