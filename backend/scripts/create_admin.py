import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.auth.password import hash_password
from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models.auth import User, UserRole


async def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update an admin user")
    parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD"))
    args = parser.parse_args()
    if not args.email or not args.password:
        parser.error("Provide --email and --password or set ADMIN_EMAIL and ADMIN_PASSWORD")
    email = args.email.lower()
    async with async_session_factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user:
            user.password_hash = hash_password(args.password)
            user.role = UserRole.admin
            user.is_active = True
        else:
            session.add(
                User(
                    email=email,
                    password_hash=hash_password(args.password),
                    role=UserRole.admin,
                    is_active=True,
                )
            )
        await session.commit()
    print(f"Admin user ready: {email}")


if __name__ == "__main__":
    asyncio.run(main())
