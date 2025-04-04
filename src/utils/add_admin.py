import asyncio

from src.database.database import get_db
from src.database.models import User

USER_ID_TELEGRAM = 380664650
PASSWORD_TELEGRAM = "51b8d695665701b71ec960af1bfa389f685ac79260e99d02662488bc0b22b8a8"


async def main():
    admin_user_id = USER_ID_TELEGRAM
    async with get_db() as session:
        await User.add_admin(session, admin_user_id, PASSWORD_TELEGRAM)
        print("Администратор успешно добавлен!")


if __name__ == "__main__":
    asyncio.run(main())
