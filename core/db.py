from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from core.settings import settings
from core.declarative_base import Base

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# SQLite will create the database file itself, but never the parent
# directory - make sure it exists before any engine tries to connect.
settings.lcms_db_path.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = settings.db_url

engine = create_async_engine(DATABASE_URL)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

SYNC_DATABASE_URL = f"sqlite:///{settings.lcms_db_path}"
sync_engine = create_engine(SYNC_DATABASE_URL)
SyncSessionLocal = sessionmaker(bind=sync_engine)

async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session