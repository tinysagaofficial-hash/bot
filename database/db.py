from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from database.models import Base
from config import DATABASE_URL

_is_postgres = DATABASE_URL.startswith("postgresql")

if _is_postgres:
    # PostgreSQL connection pool tuned for 700+ users
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_pre_ping=True,
    )
else:
    # SQLite uses NullPool and rejects pool_size/max_overflow/pool_timeout
    engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
