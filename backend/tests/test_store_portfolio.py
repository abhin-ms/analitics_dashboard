"""Store portfolio: target pro-rating and pace maths, lead-source grouping,
the action plan, extra review columns from the sheet, and the endpoint
end-to-end (in-memory SQLite, MCP back-fill switched off).
"""
from datetime import date, datetime

import pytest

from types import SimpleNamespace as NS

from app.services.store_portfolio import (
    analyse, area_of_sheet, area_of_store, attribute_lead, best_of, group_duplicates, lead_source_bucket, pace,
    prorated_target, shop_of, shops_mentioned,
)
from app.services.xlsx_reader import _daily_input_column_map, _extra_review_columns


def test_monthly_target_is_prorated_by_each_months_days():
    assert prorated_target(1_000_000, date(2026, 9, 1), date(2026, 9, 30)) == pytest.approx(1_000_000)
    assert prorated_target(1_000_000, date(2026, 9, 1), date(2026, 9, 1)) == pytest.approx(33_333.33, abs=0.01)
    # 10 Sep days + 10 Oct days
    assert prorated_target(310_000, date(2026, 9, 21), date(2026, 10, 10)) == pytest.approx(
        310_000 * 10 / 30 + 310_000 * 10 / 31)
    assert prorated_target(0, date(2026, 9, 1), date(2026, 9, 30)) == 0


def test_pace_mid_month():
    # 20 of 30 days gone, 650k views against a 1M month: 65%, behind pace
    p = pace(1_000_000, 650_000, date(2026, 9, 1), date(2026, 9, 30), today=date(2026, 9, 20))
    assert p.days_elapsed == 20 and p.days_remaining == 10
    assert p.pct == 65.0 and p.remaining == 350_000
    assert p.required_daily == pytest.approx(35_000)
    assert p.status == "on_track"  # 650k vs 666.7k expected by the 20th = 97.5% of pace
    assert pace(1_000_000, 550_000, date(2026, 9, 1), date(2026, 9, 30), date(2026, 9, 20)).status == "behind"
    assert pace(1_000_000, 400_000, date(2026, 9, 1), date(2026, 9, 30), date(2026, 9, 20)).status == "at_risk"
    ahead = pace(300_000, 280_000, date(2026, 9, 1), date(2026, 9, 30), today=date(2026, 9, 20))
    assert ahead.status == "ahead" and ahead.required_daily == pytest.approx(2_000)
    done = pace(100, 120, date(2026, 9, 1), date(2026, 9, 30), today=date(2026, 9, 20))
    assert done.status == "achieved" and done.required_daily == 0
    # sheet figures up to the 15th are judged against the target by the 15th
    mid = pace(1_000_000, 500_000, date(2026, 9, 1), date(2026, 9, 30), today=date(2026, 9, 20), as_of=date(2026, 9, 15))
    assert mid.expected_to_date == pytest.approx(500_000) and mid.status == "ahead" and mid.days_remaining == 10
    past = pace(100, 50, date(2026, 8, 1), date(2026, 8, 31), today=date(2026, 9, 20))
    assert past.days_remaining == 0 and past.required_daily is None and past.status == "at_risk"
    assert pace(0, 10, date(2026, 9, 1), date(2026, 9, 30), date(2026, 9, 5)).status == "no_target"


def test_lead_sources_map_to_the_seven_buckets():
    assert lead_source_bucket("meta_sheet") == "performance_marketing"
    assert lead_source_bucket("instagram") == "performance_marketing"
    assert lead_source_bucket("referral") == "growth_marketing"
    assert lead_source_bucket("phone") == "inbound_calls"
    assert lead_source_bucket("walk_in") == "walk_ins"
    assert lead_source_bucket("something_new") == "growth_marketing"
    # the city sheets' own PM / GM tag wins over the channel
    assert lead_source_bucket("meta_sheet", "GM") == "growth_marketing"
    assert lead_source_bucket("meta_sheet", " pm ") == "performance_marketing"


def test_store_names_resolve_to_one_shop_per_place():
    same = [("TVM", "Kerala Trivandrum"), ("PAT", "Kerala Pathanamthitta"), ("Kasaragod", "Kerala Kasargod"),
            ("Bangalore - Indira Nagar", "Bangalore Indiranagar"), ("TN - Kodambakkam", "Chennai Kodambakam"),
            ("Mumbai - Korum Mall", "Mumbai Korum")]
    for a, b in same:
        assert shop_of(a) == shop_of(b) is not None, (a, b)
    assert shop_of("Delhi Lajpat Nagar") == "lajpat_nagar" and shop_of("Delhi") == "delhi"
    for placeholder in ("Kerala Store", "Delhi Store", "Chennai Store", "Mumbai Store"):
        assert shop_of(placeholder) is None and area_of_store(placeholder) is not None
    assert area_of_store("Bahrain") is None and shop_of("Store Name") is None
    assert area_of_sheet("Guwahati") == "assam" and area_of_sheet("Delhi") == "north"
    assert shops_mentioned("visit the kukatpally store", "north") == {"kukatpally"}
    assert shops_mentioned("once reach bangalore", "karnataka") == set()


def test_lead_attribution_rules():
    base = dict(store_shop=None, appointment_shop=None, remarks_shops=set(), lead_area="kerala",
                target_shop="kochi", target_area="kerala", area_shop_count=11)
    assert attribute_lead(**{**base, "store_shop": "kochi"}) == ("store", "store on the lead")
    assert attribute_lead(**{**base, "store_shop": "kollam"})[0] is None
    assert attribute_lead(**{**base, "appointment_shop": "kochi"}) == ("store", "appointment at the store")
    assert attribute_lead(**{**base, "remarks_shops": {"kochi"}}) == ("store", "shop named in remarks")
    assert attribute_lead(**{**base, "remarks_shops": {"kollam"}})[0] is None
    assert attribute_lead(**base) == ("area", "shop not known")
    assert attribute_lead(**{**base, "lead_area": "assam"})[0] is None
    one = {**base, "lead_area": "assam", "target_shop": "guwahati", "target_area": "assam", "area_shop_count": 1}
    assert attribute_lead(**one) == ("store", "only shop in the area")


def test_same_person_within_a_week_is_one_lead():
    t = datetime(2026, 9, 1)
    leads = [NS(phone="+91 98765 43210", status="", at=t),
             NS(phone="9876543210", status="Appointment", at=t.replace(day=3)),   # Meta/website copy
             NS(phone="09876543210", status="", at=t.replace(day=25)),            # came back weeks later
             NS(phone="", status="", at=t)]
    groups = group_duplicates(leads, lambda l: l.at)
    assert sorted(len(g) for g in groups) == [1, 1, 2]
    assert best_of(next(g for g in groups if len(g) == 2)).status == "Appointment"


def test_action_plan_flags_what_is_behind():
    today = date(2026, 9, 20)
    views = pace(1_000_000, 400_000, date(2026, 9, 1), date(2026, 9, 30), today).as_dict()
    social = {"has_data": True, "views": views, "reels": 20}
    vol = pace(3000, 2100, date(2026, 9, 1), date(2026, 9, 30), today).as_dict()
    conv = pace(300, 168, date(2026, 9, 1), date(2026, 9, 30), today).as_dict()
    leads = {"volume": vol, "conversions": conv, "untouched": 120, "warm": 900,
             "conversion_pct": 8.0, "conversion_target_pct": 10, "best_source": {"label": "WhatsApp", "rate": 10.0}}
    sales = {"pace": pace(300_000, 280_000, date(2026, 9, 1), date(2026, 9, 30), today).as_dict(), "avg_bill": 1667}
    reviews = {"rating": 4.6, "new_reviews": 32, "negative": 4, "unanswered": 3, "response": "Partial"}
    out = analyse(social, leads, sales, reviews, lambda x: f"₹{round(x):,}")
    rows = {r["area"]: r for r in out["rows"]}
    assert rows["social"]["priority"] == "High" and "views/day" in rows["social"]["action"]
    assert "120 leads with no status" in rows["leads"]["action"]
    assert rows["sales"]["status"] == "ahead" and "12 sales" in rows["sales"]["gap"]
    assert "3 unanswered" in rows["reviews"]["action"]
    assert "social" in out["needs_attention"]
    assert any("Conversion 8.0%" in c for c in out["concerns"])


def test_missing_data_is_said_plainly():
    out = analyse({"has_data": False, "last_report": {"as_of": "2026-09-30", "instagram": 2_030_000, "instagram_pct": 203.0}}, {}, {"pace": {"status": "no_target"}}, {"rating": None}, str)
    statuses = {r["area"]: r["status"] for r in out["rows"]}
    assert statuses == {"social": "no_data", "sales": "no_target", "reviews": "no_data"}
    assert "last report 2026-09-30: 2,030,000 views (203.0% of target)" in out["rows"][0]["gap"]


def test_new_google_review_columns_in_the_sheet_are_picked_up():
    section = ["", "", "", "", "SALES", None, "GOOGLE", None, None, None, "MISC"]
    header = ["Date", "Store Name", "Country", "Store Type", "Daily Revenue", "Monthly Target",
              "Google Rating", "New Reviews", "Positive Reviews", "Negative reviews", "Notes"]
    col_map = _daily_input_column_map(section, header)
    extra = _extra_review_columns(section, header, col_map)
    assert extra == {"Positive Reviews": 8, "Negative reviews": 9}


# ── endpoint ─────────────────────────────────────────────────────────
pytest.importorskip("aiosqlite")
pytest.importorskip("pytest_asyncio")

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.deps import get_current_user  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.models import (  # noqa: E402
    DailyStoreTracker, McpDailySale, Role, Store, StoreMcpAlias, TeleAppointment, TeleCallLead, User,
)
from app.services import sales_report_service  # noqa: E402

# A finished month, so nothing depends on today's date.
MONTH = {"start": "2025-09-01", "end": "2025-09-30"}


@pytest_asyncio.fixture
async def env(monkeypatch):
    async def _no_backfill(*_a, **_k):
        return None
    monkeypatch.setattr(sales_report_service, "_ensure_mcp_coverage", _no_backfill)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with Session() as db:
        roles = {n: Role(name=n) for n in ("CEO", "Telecaller")}
        db.add_all(roles.values())
        await db.flush()
        tl = User(name="Priya", email="tl@x", password_hash="x", role_id=roles["CEO"].id)
        db.add(tl)
        await db.flush()
        a = Store(name="Indiranagar", team_leader_id=tl.id, country="India", monthly_target=300_000)
        b = Store(name="Other", team_leader_id=tl.id, country="India")
        mysore = Store(name="Mysore", team_leader_id=tl.id, country="India")  # 2nd Karnataka shop
        placeholder = Store(name="Bangalore Store", team_leader_id=tl.id, country="India")  # area, no shop
        db.add_all([a, b, mysore, placeholder])
        await db.flush()
        u = {"ceo": tl, "caller": User(name="Tia", email="t@x", password_hash="x",
                                       role_id=roles["Telecaller"].id, store_id=b.id)}
        db.add(u["caller"])
        db.add(StoreMcpAlias(store_id=a.id, mcp_shop_name="BP Indiranagar"))
        db.add_all([McpDailySale(store_id=a.id, date=date(2025, 9, d), revenue=10_000, new_sale_count=6)
                    for d in range(1, 31)])  # 3,00,000 from 180 sales
        # Month-to-date rows: the store moved its September row from the 10th
        # to the 20th; the sync keeps both, only the latest is September's.
        db.add_all([
            DailyStoreTracker(store_id=a.id, date="2025-03-31", store_name="Indiranagar",
                              ig_views_achieved=111),  # > 6 months before the end of the year
            DailyStoreTracker(store_id=a.id, date="2025-08-31", store_name="Indiranagar",
                              ig_views_achieved=900_000, google_rating=4.3),
            DailyStoreTracker(store_id=a.id, date="2025-09-10", store_name="Indiranagar", ig_videos_posted=10,
                              ig_views_achieved=300_000, ig_comments=15, google_rating=4.4, google_new_reviews=5),
            DailyStoreTracker(store_id=a.id, date="2025-09-20", store_name="Indiranagar", ig_videos_posted=18,
                              ig_views_achieved=450_000, ig_comments=40, ig_shares=7, google_rating=4.6,
                              google_new_reviews=8, google_review_response="Partial",
                              extra_fields={"Negative reviews": 2}),
            DailyStoreTracker(store_id=a.id, date="2025-10-02", store_name="Indiranagar",
                              ig_views_achieved=999_999),  # outside the month
        ])
        t = datetime(2025, 9, 5, 6, 0)
        leads = [
            TeleCallLead(sheet_tl_name="K", full_name="A", phone="9876500001", store_id=a.id, spreadsheet_id="s", lead_source="PM",
                         status="Sale Conversion", sale_amount="12,000", created_at=t, submitted_at=t),
            TeleCallLead(sheet_tl_name="K", full_name="B", phone="2", store_id=a.id, spreadsheet_id="s", lead_source="GM",
                         status="", created_at=t, submitted_at=t),
            TeleCallLead(sheet_tl_name="K", full_name="C", phone="3", store_id=a.id, source_channel="whatsapp",
                         status="Will Visit", created_at=t, submitted_at=t),
            TeleCallLead(sheet_tl_name="K", full_name="D", phone="4", store_id=b.id, source_channel="website",
                         status="Sale Conversion", sale_amount="9,999", created_at=t, submitted_at=t),
        ]
        leads += [
            # same person again from the website two days later: one lead
            TeleCallLead(sheet_tl_name="K", full_name="A", phone="+91 98765 00001", store_id=a.id,
                         source_channel="website", status="", created_at=t.replace(day=7), submitted_at=t.replace(day=7)),
            # Bangalore sheet, no store: Karnataka has two shops, so an area lead
            TeleCallLead(sheet_tl_name="Bangalore", full_name="E", phone="9876500005", spreadsheet_id="s",
                         lead_source="PM", status="", created_at=t, submitted_at=t),
            # a Meta lead whose ad set matched the placeholder "Bangalore Store":
            # not a shop, so it belongs in the Karnataka area pool, not nowhere
            TeleCallLead(sheet_tl_name="Bangalore", full_name="G", phone="9876500007", source_channel="facebook",
                         store_id=placeholder.id, status="", created_at=t, submitted_at=t),
            # Bangalore sheet, remarks name the shop
            TeleCallLead(sheet_tl_name="Bangalore", full_name="F", phone="9876500006", spreadsheet_id="s",
                         lead_source="GM", remarks="will visit indiranagar store", status="", created_at=t, submitted_at=t),
        ]
        db.add_all(leads)
        await db.flush()
        db.add(TeleAppointment(lead_id=leads[2].id, store_id=a.id, scheduled_at=t, attendance="attended"))
        await db.commit()
        ids = {k: v.id for k, v in u.items()}
        store_ids = {"a": a.id, "b": b.id}

    state = {"user": None}

    async def _db():
        async with Session() as s:
            yield s

    async def _user():
        async with Session() as s:
            return (await s.execute(
                select(User).where(User.id == state["user"]).options(selectinload(User.store_access))
            )).scalar_one()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        def as_user(key):
            state["user"] = ids[key]
            return client
        as_user.stores = store_ids
        yield as_user
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_portfolio_end_to_end(env):
    r = await env("ceo").get(f"/api/v1/store-portfolio/{env.stores['a']}", params=MONTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["store"]["name"] == "Indiranagar" and body["store"]["currency"] == "INR"

    sales = body["sales"]
    assert sales["pace"]["achieved"] == 300_000 and sales["pace"]["pct"] == 100.0
    assert sales["avg_bill"] == pytest.approx(1666.67, abs=0.01) and sales["sales_count"] == 180
    assert sales["series"][-1]["cumulative"] == 300_000

    social = body["social"]
    # September's latest month-to-date row (the 20th), judged against the
    # target expected by the 20th: 450k of 666,667
    assert social["as_of"] == "2025-09-20"
    assert social["views"]["achieved"] == 450_000 and social["views"]["target"] == pytest.approx(1_000_000)
    assert social["views"]["expected_to_date"] == pytest.approx(666_666.67, abs=0.01)
    assert social["reels"] == 18 and social["comments"] == 40
    assert [m["month"] for m in social["monthly"]] == ["2025-08", "2025-09"]

    leads = body["leads"]
    assert leads["total"] == 4 and leads["converted"] == 1 and leads["untouched"] == 2
    assert leads["duplicates_merged"] == 1  # A's website copy
    assert leads["matched_by"] == {"store on the lead": 3, "shop named in remarks": 1}
    src = {s["key"]: s for s in leads["sources"]}
    assert src["performance_marketing"]["leads"] == 1 and src["performance_marketing"]["revenue"] == 12_000
    assert src["growth_marketing"]["leads"] == 2  # sheet-tagged GM: B and F
    assert leads["area"]["label"] == "Karnataka" and leads["area"]["total"] == 2 and leads["area"]["shops"] == 2
    assert src["whatsapp"]["leads"] == 1 and src["website"]["leads"] == 0  # store B's lead isn't here
    assert leads["visits"]["attended"] == 1

    reviews = body["reviews"]
    assert reviews["rating"] == 4.6 and reviews["rating_as_of"] == "2025-09-20"
    assert reviews["new_reviews"] == 8 and reviews["negative"] == 2
    assert reviews["response"] == "Partial"

    areas = {row["area"]: row for row in body["analysis"]["rows"]}
    assert set(areas) == {"social", "leads", "sales", "reviews"}
    assert areas["sales"]["status"] == "achieved"
    assert areas["social"]["status"] == "at_risk"


@pytest.mark.asyncio
async def test_portfolio_respects_store_access(env):
    r = await env("caller").get(f"/api/v1/store-portfolio/{env.stores['a']}", params=MONTH)
    assert r.status_code == 403
    r = await env("caller").get(f"/api/v1/store-portfolio/{env.stores['b']}", params=MONTH)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_portfolio_rejects_bad_ranges(env):
    sid = env.stores["a"]
    assert (await env("ceo").get(f"/api/v1/store-portfolio/{sid}",
                                 params={"start": "2025-09-30", "end": "2025-09-01"})).status_code == 400
    assert (await env("ceo").get(f"/api/v1/store-portfolio/{sid}",
                                 params={"start": "2020-01-01", "end": "2025-09-01"})).status_code == 400


@pytest.mark.asyncio
async def test_year_range_reads_the_whole_year_of_tracker_rows(env):
    r = await env("ceo").get(f"/api/v1/store-portfolio/{env.stores['a']}",
                             params={"start": "2025-01-01", "end": "2025-12-31"})
    social = r.json()["social"]
    assert "2025-03" in [m["month"] for m in social["monthly"]]
    # March + August + September (latest Sept row) + October
    assert social["views"]["achieved"] == 111 + 900_000 + 450_000 + 999_999
