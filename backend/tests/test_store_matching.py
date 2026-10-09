"""Leads find their store: place names in Meta form names / website store
text match the right shop, a duplicate store record without a team leader
gives way to the one with one, and the admin fix-up previews before it
routes anything (hand-mapped forms and owned leads are left alone).

Needs `aiosqlite` (skipped otherwise): pip install aiosqlite
"""
from datetime import datetime

import pytest

pytest.importorskip("aiosqlite")
pytest.importorskip("pytest_asyncio")

import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.models.models import (  # noqa: E402
    MetaFormStore, MetaLead, Role, Store, StoreMcpAlias, TeleCallLead, User,
)
from app.services.crm.intake import match_store  # noqa: E402
from app.services.crm.store_rematch import rematch_stores  # noqa: E402


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as s:
        roles = {n: Role(name=n) for n in ("Admin", "Team Leader", "Telecaller")}
        s.add_all(roles.values())
        await s.flush()
        admin = User(name="Ada", email="a@x", password_hash="x", role_id=roles["Admin"].id)
        nobody = User(name="Unassigned", email="u@x", password_hash="x", role_id=roles["Team Leader"].id)
        michael = User(name="Michael", email="m@x", password_hash="x", role_id=roles["Team Leader"].id)
        abdullah = User(name="Abdullah", email="ab@x", password_hash="x", role_id=roles["Team Leader"].id)
        sam = User(name="Sam", email="s@x", password_hash="x", role_id=roles["Team Leader"].id)
        s.add_all([admin, nobody, michael, abdullah, sam])
        await s.flush()
        caller = User(name="Tia", email="t@x", password_hash="x", role_id=roles["Telecaller"].id,
                      team_leader_id=abdullah.id)
        s.add(caller)
        stores = {
            "tvm": Store(name="TVM", team_leader_id=michael.id),
            "kt": Store(name="Kerala Trivandrum", team_leader_id=nobody.id),  # duplicate, no real TL
            "hitech": Store(name="Hyderabad - Hitech City", team_leader_id=abdullah.id),
            "kod": Store(name="TN - Kodambakkam", team_leader_id=sam.id),
            "bandra": Store(name="Mumbai Bandra", team_leader_id=abdullah.id),
        }
        s.add_all(stores.values())
        await s.flush()
        s.add(StoreMcpAlias(store_id=stores["tvm"].id, mcp_shop_name="BP TVM"))
        await s.commit()
        s.info.update({"admin": admin, "caller": caller, "stores": stores})
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_place_names_find_the_right_store(db):
    st = db.info["stores"]
    cases = {
        "Hitech City North - 18 September 2026 - OTP Verify": st["hitech"],
        "Kodambakkam, Chennai": st["kod"],
        "Kazhakkoottam, Trivandrum": st["tvm"],   # Trivandrum shop → the TVM record (has a TL)
        "Kerala Trivandrum": st["tvm"],           # exact name of the empty duplicate → swapped
        "TVM": st["tvm"],
    }
    for text, want in cases.items():
        got = await match_store(db, text, "")
        assert got is not None and got.id == want.id, text
    for vague in ("Nearest store (Karnataka)", "Burjuman Mall", "Thane-New-Final"):
        assert await match_store(db, vague, "") is None, vague


@pytest.mark.asyncio
async def test_fixup_previews_then_routes(db):
    st, admin = db.info["stores"], db.info["admin"]
    t = datetime.utcnow()
    db.add_all([
        MetaFormStore(form_id="F-HITECH", form_name="Hitech City North - 18 September 2026 - OTP Verify"),
        MetaFormStore(form_id="F-TVM", form_name="TVM - 18 September 2026 - OTP Verify",
                      store_id=st["kt"].id, match_source="auto"),
        MetaFormStore(form_id="F-HAND", form_name="Hitech City West", store_id=st["bandra"].id,
                      match_source="manual"),  # an admin's choice: never changed
    ])
    meta_lead = TeleCallLead(sheet_tl_name="Meta", full_name="Sai", phone="9000000001", source_channel="instagram",
                             spreadsheet_id="", created_at=t, status="")
    web_lead = TeleCallLead(sheet_tl_name="Website", full_name="Vignesh", phone="9000000002",
                            source_channel="website", preferred_store_text="Kodambakkam, Chennai", created_at=t)
    owned = TeleCallLead(sheet_tl_name="Website", full_name="Owned", phone="9000000003", source_channel="website",
                         preferred_store_text="Kodambakkam, Chennai", owner_user_id=admin.id, created_at=t)
    db.add_all([meta_lead, web_lead, owned])
    await db.flush()
    db.add(MetaLead(leadgen_id="G1", form_id="F-HITECH", lead_id=meta_lead.id, status="created"))
    await db.commit()

    preview = await rematch_stores(db, admin, apply=False)
    forms = {f["form"]: f for f in preview["forms"]}
    assert forms["Hitech City North - 18 September 2026 - OTP Verify"]["to"] == "Hyderabad - Hitech City"
    assert forms["Hitech City North - 18 September 2026 - OTP Verify"]["waiting_leads"] == 1
    assert forms["TVM - 18 September 2026 - OTP Verify"] == {
        "form": "TVM - 18 September 2026 - OTP Verify", "from": "Kerala Trivandrum", "to": "TVM",
        "team_leader": "Michael", "waiting_leads": 0}
    assert "Hitech City West" not in forms
    assert [(l["name"], l["to"]) for l in preview["leads"]] == [("Vignesh", "TN - Kodambakkam")]
    await db.refresh(web_lead)
    assert web_lead.store_id is None and web_lead.owner_user_id is None  # preview wrote nothing

    await rematch_stores(db, admin, apply=True)
    await db.refresh(meta_lead)
    await db.refresh(web_lead)
    await db.refresh(owned)
    assert meta_lead.store_id == st["hitech"].id and meta_lead.owner_user_id == db.info["caller"].id
    assert web_lead.store_id == st["kod"].id and web_lead.owner_user_id is not None
    assert owned.store_id is None and owned.owner_user_id == admin.id
    hand = await db.get(MetaFormStore, (await db.execute(
        MetaFormStore.__table__.select().where(MetaFormStore.form_id == "F-HAND"))).first().id)
    assert hand.store_id == st["bandra"].id
