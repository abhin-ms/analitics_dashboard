"""The Operations sheet's TL column names a team leader per store. It may set
the team leader of a store it creates, but must not undo a reassignment
made in the app on every sync.

Needs `aiosqlite` (skipped otherwise): pip install aiosqlite
"""
import pytest

pytest.importorskip("aiosqlite")
pytest.importorskip("pytest_asyncio")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.models.models import Role, Store, User  # noqa: E402
from app.services.sheet_sync_service import SheetSyncService  # noqa: E402


@pytest.mark.asyncio
async def test_sheet_sync_keeps_team_leader_set_in_app():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    sync = SheetSyncService()
    async with Session() as db:
        role = Role(name="Team Leader")
        db.add(role)
        await db.flush()
        sam = await sync._get_or_create_tl(db, "Sam", role.id)
        new_tl = User(name="New TL", email="n@x", password_hash="x", role_id=role.id)
        db.add(new_tl)
        await db.flush()

        store = await sync._get_or_create_store(db, "Coimbatore", sam.id)
        assert store.team_leader_id == sam.id  # a new store takes the sheet's TL

        store.team_leader_id = new_tl.id  # reassigned on the Stores page
        await db.commit()
        again = await sync._get_or_create_store(db, "Coimbatore", sam.id)  # next sheet sync
        assert again.id == store.id
        assert again.team_leader_id == new_tl.id
    await engine.dispose()
