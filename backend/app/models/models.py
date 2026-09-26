from datetime import datetime, date
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, DateTime, Date,
    ForeignKey, Numeric, JSON, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship, backref
from ..db.base import Base


# ── Currencies ──────────────────────────────────────────────────────
class Currency(Base):
    __tablename__ = "currencies"
    code = Column(String(3), primary_key=True)
    name = Column(String(50), nullable=False)
    symbol = Column(String(5), nullable=False)
    decimal_places = Column(Integer, default=2)
    number_format_style = Column(String(10), default="indian")


# ── Exchange Rates ──────────────────────────────────────────────────
class ExchangeRate(Base):
    __tablename__ = "exchange_rates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    currency_code = Column(String(3), ForeignKey("currencies.code"), nullable=False)
    rate_to_base = Column(Numeric(14, 6), nullable=False)
    effective_date = Column(Date, nullable=False)
    source = Column(String(50), default="manual")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("currency_code", "effective_date"),
    )


# ── Roles ──────────────────────────────────────────────────────────
class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    permissions = relationship("Permission", secondary="role_permissions", back_populates="roles")


# ── Permissions ────────────────────────────────────────────────────
class Permission(Base):
    __tablename__ = "permissions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    resource = Column(String(50), nullable=False)
    action = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    roles = relationship("Role", secondary="role_permissions", back_populates="permissions")

    __table_args__ = (
        UniqueConstraint("resource", "action"),
    )


# ── Role ↔ Permission join ─────────────────────────────────────────
class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id = Column(Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)


# ── Users ──────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    email = Column(String(200), unique=True, nullable=False, index=True)
    password_hash = Column(String(200), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    invite_token = Column(String(200), nullable=True)
    invite_expires_at = Column(DateTime, nullable=True)
    # Single assigned store (Telecaller/Salesperson — one store each). Not
    # used for Team Leader (see Store.team_leader_id, one-to-many) or
    # Regional Manager (see UserStoreAccess, an explicit multi-store grant).
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True)
    # Explicit "reports to" link for Telecaller/Salesperson, replacing the
    # old implicit inference-by-shared-sheet-name for this specific question.
    team_leader_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Telecalling CRM: a telecaller can mark themselves "Away" so automatic
    # round-robin assignment and 15-minute reassignment skip them.
    available_for_leads = Column(Boolean, default=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    role = relationship("Role", backref="users")
    store_access = relationship("UserStoreAccess", back_populates="user", cascade="all, delete-orphan")
    store = relationship("Store", foreign_keys=[store_id])
    manager = relationship("User", remote_side=[id], foreign_keys=[team_leader_id])


# ── User ↔ Store access ───────────────────────────────────────────
class UserStoreAccess(Base):
    __tablename__ = "user_store_access"
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="store_access")
    store = relationship("Store", back_populates="users_with_access")


# ── Stores ─────────────────────────────────────────────────────────
class Store(Base):
    __tablename__ = "stores"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    team_leader_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    currency_code = Column(String(3), ForeignKey("currencies.code"), default="INR")
    daily_target = Column(Numeric(14, 2), default=0)
    monthly_target = Column(Numeric(14, 2), default=0)
    breakeven_revenue = Column(Numeric(14, 2), default=0)
    profitability_target = Column(Numeric(14, 2), default=0)
    fixed_costs = Column(Numeric(14, 2), default=0)
    variable_cost_pct = Column(Numeric(5, 2), default=0)
    is_active = Column(Boolean, default=True)
    region = Column(String(50), default="")
    # Free-text street address and an optional Google Maps link, so the
    # Instagram bot (and staff) can give a customer a real location —
    # previously nowhere in the system, only the short region code above.
    address = Column(Text, nullable=True)
    maps_link = Column(String(500), nullable=True)
    country = Column(String(50), default="India")
    mcp_country_id = Column(Integer, nullable=True)
    mcp_shop_name = Column(String(150), nullable=True, unique=True)
    needs_review = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    team_leader = relationship("User", foreign_keys=[team_leader_id])
    currency = relationship("Currency", backref="stores")
    users_with_access = relationship("UserStoreAccess", back_populates="store")


# ── Store MCP Aliases ────────────────────────────────────────────────
# Permanent memory of every MCP shop name ever confirmed to belong to a
# given Store, independent of Store.mcp_shop_name (which only holds the
# CURRENT/most-recent one). Without this, merging a duplicate branch away
# deletes the only record that a given MCP name was ever resolved — so the
# next time MCP sends a sale under that same name, the system has no memory
# of the earlier decision and creates a fresh "needs review" branch all over
# again, forever. Recording every confirmed name here means a shop only
# ever needs to be identified once, no matter how many times its name
# resurfaces afterward.
class StoreMcpAlias(Base):
    __tablename__ = "store_mcp_aliases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    mcp_shop_name = Column(String(150), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # passive_deletes=True defers to the DB's ON DELETE CASCADE (above)
    # instead of the ORM's own default behavior of nulling out store_id on
    # related rows before deleting the parent Store — which would otherwise
    # fail outright since store_id is NOT NULL.
    store = relationship("Store", backref=backref("mcp_aliases", passive_deletes=True))


# ── Daily Submissions ──────────────────────────────────────────────
class DailySubmission(Base):
    __tablename__ = "daily_submissions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    date = Column(Date, nullable=False)
    revenue = Column(Numeric(14, 2), default=0)
    units_sold = Column(Integer, default=0)
    care_plus_attached = Column(Integer, default=0)
    new_leads = Column(Integer, default=0)
    active_leads = Column(Integer, default=0)
    calls_made = Column(Integer, default=0)
    calls_connected = Column(Integer, default=0)
    walk_ins = Column(Integer, default=0)
    walk_in_conversions = Column(Integer, default=0)
    staff_on_duty = Column(Integer, default=0)
    training_done = Column(Boolean, default=False)
    training_topic = Column(String(200), default="")
    stock_opening = Column(Integer, default=0)
    stock_received = Column(Integer, default=0)
    stock_sold = Column(Integer, default=0)
    stock_closing = Column(Integer, default=0)
    stock_variance = Column(Integer, default=0)
    cash_opening = Column(Numeric(14, 2), default=0)
    cash_sales = Column(Numeric(14, 2), default=0)
    bank_deposit = Column(Numeric(14, 2), default=0)
    petty_cash_note = Column(Text, default="")
    cash_closing = Column(Numeric(14, 2), default=0)
    installations = Column(Integer, default=0)
    service_calls = Column(Integer, default=0)
    complaints_in = Column(Integer, default=0)
    complaints_resolved = Column(Integer, default=0)
    app_updated = Column(Boolean, default=False)
    notes = Column(Text, default="")
    google_review_rating = Column(Float, nullable=True)
    submitted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    store = relationship("Store", backref="submissions")
    submitter = relationship("User", foreign_keys=[submitted_by])

    __table_args__ = (
        UniqueConstraint("store_id", "date"),
        Index("ix_submissions_store_date", "store_id", "date"),
    )


# ── Leads ──────────────────────────────────────────────────────────
class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    source = Column(String(20), nullable=False, default="inbound")
    name = Column(String(100), nullable=False)
    phone = Column(String(20), default="")
    status = Column(String(20), default="warm")
    stage = Column(String(50), default="new")
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_contacted_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    store = relationship("Store", backref="leads")
    assignee = relationship("User", foreign_keys=[assigned_to])


# ── Lead Activities ────────────────────────────────────────────────
class LeadActivity(Base):
    __tablename__ = "lead_activities"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(20), nullable=False)
    outcome = Column(String(50), default="")
    notes = Column(Text, default="")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    lead = relationship("Lead", backref="activities")
    creator = relationship("User", foreign_keys=[created_by])


# ── Lost Reasons ───────────────────────────────────────────────────
class LostReason(Base):
    __tablename__ = "lost_reasons"
    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    date = Column(Date, nullable=False)
    reason = Column(String(50), nullable=False)
    count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    store = relationship("Store", backref="lost_reasons")


# ── Campaigns ──────────────────────────────────────────────────────
class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    channel = Column(String(50), default="")
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    budget = Column(Numeric(14, 2), default=0)
    status = Column(String(20), default="draft")
    success_rate = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Tasks ──────────────────────────────────────────────────────────
class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    type = Column(String(20), default="task")
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True)
    due_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="pending")
    priority = Column(String(10), default="medium")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assignee = relationship("User", foreign_keys=[assigned_to])
    store = relationship("Store", backref="tasks")


# ── KPI Weights ────────────────────────────────────────────────────
class KPIWeight(Base):
    __tablename__ = "kpi_weights"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kpi_name = Column(String(100), unique=True, nullable=False)
    description = Column(String(200), default="")
    weight = Column(Numeric(4, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Incentive Bands ────────────────────────────────────────────────
class IncentiveBand(Base):
    __tablename__ = "incentive_bands"
    id = Column(Integer, primary_key=True, autoincrement=True)
    band_name = Column(String(50), nullable=False)
    min_kpi_score = Column(Numeric(4, 2), nullable=False)
    multiplier = Column(Numeric(4, 2), nullable=False)
    label = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Google Reviews ─────────────────────────────────────────────────
class GoogleReview(Base):
    __tablename__ = "google_reviews"
    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    date = Column(Date, nullable=False)
    rating = Column(Float, default=0)
    total_reviews = Column(Integer, default=0)
    new_reviews = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    store = relationship("Store", backref="google_reviews")


# ── Investments ────────────────────────────────────────────────────
class Investment(Base):
    __tablename__ = "investments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True)
    category = Column(String(50), nullable=False)
    description = Column(String(200), default="")
    amount = Column(Numeric(14, 2), nullable=False)
    date = Column(Date, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    store = relationship("Store", backref="investments")
    creator = relationship("User", foreign_keys=[created_by])


# ── Sheet Sources ──────────────────────────────────────────────────
class SheetSource(Base):
    __tablename__ = "sheet_sources"
    id = Column(Integer, primary_key=True, autoincrement=True)
    label = Column(String(100), nullable=False)
    spreadsheet_id = Column(String(200), nullable=False)
    is_xlsx_upload = Column(Boolean, default=False)
    sync_interval_minutes = Column(Integer, default=5)
    is_enabled = Column(Boolean, default=True)
    tab_mappings = Column(JSON, default=dict)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Sheet Sync Log ─────────────────────────────────────────────────
class SheetSyncLog(Base):
    __tablename__ = "sheet_sync_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sheet_source_id = Column(Integer, ForeignKey("sheet_sources.id", ondelete="CASCADE"), nullable=False)
    tab_name = Column(String(100), default="")
    last_synced_at = Column(DateTime, nullable=True)
    rows_synced = Column(Integer, default=0)
    status = Column(String(20), default="pending")
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    source = relationship("SheetSource", backref="sync_logs")


# ── Audit Log ──────────────────────────────────────────────────────
class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(50), nullable=False)
    resource = Column(String(50), nullable=False)
    resource_id = Column(Integer, nullable=True)
    before_json = Column(JSON, nullable=True)
    after_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])


# ── Settings ───────────────────────────────────────────────────────
class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(100), primary_key=True)
    value = Column(Text, default="")
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── CEO Dashboard: Marketing Metrics (per store per month) ──────────
class MarketingMetrics(Base):
    __tablename__ = "marketing_metrics"
    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    month = Column(String(7), nullable=False)  # "2026-06"
    ig_videos_posted = Column(Integer, nullable=True)
    ig_views = Column(Integer, nullable=True)
    ig_followers = Column(Integer, nullable=True)
    ig_new_followers = Column(Integer, nullable=True)
    ig_likes = Column(Integer, nullable=True)
    ig_comments = Column(Integer, nullable=True)
    ig_dms_received = Column(Integer, nullable=True)
    ig_manychat_handled = Column(Integer, nullable=True)
    ig_posts = Column(Integer, nullable=True)
    wa_walkins = Column(Integer, default=0)
    google_rating = Column(Float, nullable=True)
    google_new_reviews = Column(Integer, nullable=True)
    google_review_response = Column(String(20), default="")  # Yes/Partial/No
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    store = relationship("Store")


# ── CEO Dashboard: Store Staff / People ─────────────────────────────
class StoreStaff(Base):
    __tablename__ = "store_staff"
    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    month = Column(String(7), nullable=False)  # "2026-06"
    manager_name = Column(String(100), default="")
    staff_count = Column(Integer, default=0)
    total_headcount = Column(Integer, default=0)
    has_accommodation = Column(Boolean, default=False)
    resignation_risk = Column(Integer, default=0)
    training_active = Column(Boolean, default=False)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    store = relationship("Store")


# ── CEO Dashboard: International Stores ─────────────────────────────
class InternationalStore(Base):
    __tablename__ = "international_stores"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    country = Column(String(20), nullable=False)  # UAE, Oman
    region = Column(String(20), nullable=False)    # AUH, DXB, AJM, OMN
    month = Column(String(7), nullable=False)      # "2026-06"
    target = Column(Numeric(14, 2), nullable=True)
    actual = Column(Numeric(14, 2), default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── CEO Dashboard: Strategic Insights ───────────────────────────────
class StrategicInsight(Base):
    __tablename__ = "strategic_insights"
    id = Column(Integer, primary_key=True, autoincrement=True)
    month = Column(String(7), nullable=False)
    category = Column(String(20), nullable=False)  # critical, warning, good, info
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    action_tag = Column(Text, default="")
    assigned_to = Column(Text, default="")
    section = Column(String(50), default="overview")  # overview, ops, tl, intl, marketing, reviews, actions
    priority = Column(String(20), default="high")      # critical, high, strategic
    deadline = Column(String(20), default="")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    # "manual" (human-authored or synced from the gr_action_plan Sheet, the
    # long-standing behavior) vs "auto" (written by insight_engine.py from
    # real data patterns). rule_key identifies which specific rule+entity
    # produced an auto row, so each engine run can cleanly replace only its
    # own previous output.
    source = Column(String(10), default="manual")
    rule_key = Column(String(150), nullable=True)

    __table_args__ = (
        Index("ix_insight_month_section", "month", "section"),
        Index("ix_insight_month_source", "month", "source"),
    )


# ── Insight Resolution Log (feedback loop for the auto insight engine) ──
class InsightResolutionLog(Base):
    """One row per auto-detected rule_key, tracking when it was first
    raised, last confirmed still triggering, and when it stopped (was
    resolved) — see insight_engine.py. This is what lets the insight
    engine's real-world usefulness be measured (resolution rate, time to
    resolve) instead of just trusting the rules are well-tuned."""
    __tablename__ = "insight_resolution_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_key = Column(String(150), nullable=False, unique=True)
    title = Column(String(200), nullable=False)
    priority = Column(String(20), nullable=False)
    month = Column(String(7), nullable=False)
    first_detected_at = Column(DateTime, nullable=False)
    last_seen_at = Column(DateTime, nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_insight_log_month", "month"),
    )


# ── Dashboard Chat (usage/cost log) ──────────────────────────────
class DashboardChatLog(Base):
    """One row per chatbot exchange on the AI Summary chat bubble, tracked
    separately from AISummaryRun and ai_usage_log so this feature's real
    token cost is directly visible rather than guessed at."""
    __tablename__ = "dashboard_chat_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    provider = Column(String(20), nullable=False)
    model = Column(String(100), nullable=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost_estimate = Column(Numeric(10, 6), default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_chat_log_created_at", "created_at"),
    )


# ── Daily Store Tracker (from xlsx) ───────────────────────────────
class DailyStoreTracker(Base):
    __tablename__ = "daily_store_tracker"
    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    date = Column(String(30), nullable=False)
    store_name = Column(String(100), nullable=False)
    country = Column(String(10), default="")
    store_type = Column(String(50), default="")
    daily_revenue = Column(Numeric(14, 2), default=0)
    monthly_target = Column(Numeric(14, 2), default=0)
    mtd_revenue = Column(Numeric(14, 2), default=0)
    units_sold = Column(Integer, default=0)
    care_plus_attached = Column(Integer, default=0)
    prebookings = Column(Integer, default=0)
    ig_videos_posted = Column(Integer, default=0)
    ig_views_target = Column(Numeric(14, 2), default=0)
    ig_views_achieved = Column(Numeric(14, 2), default=0)
    ig_views_achd_pct = Column(Float, default=0)
    ig_followers = Column(Integer, default=0)
    ig_new_followers = Column(Integer, default=0)
    ig_likes = Column(Integer, default=0)
    ig_comments = Column(Integer, default=0)
    ig_saves = Column(Integer, default=0)
    ig_shares = Column(Integer, default=0)
    ig_reposts = Column(Integer, default=0)
    ig_dms_received = Column(Integer, default=0)
    ig_manychat_handled = Column(Integer, default=0)
    ig_posts_published = Column(Integer, default=0)
    yt_views = Column(Integer, default=0)
    yt_likes = Column(Integer, default=0)
    yt_comments = Column(Integer, default=0)
    tt_views = Column(Integer, default=0)
    tt_likes = Column(Integer, default=0)
    tt_followers = Column(Integer, default=0)
    sc_views = Column(Integer, default=0)
    sc_shares = Column(Integer, default=0)
    wa_chats_received = Column(Integer, default=0)
    wa_walkins_booked = Column(Integer, default=0)
    google_rating = Column(Float, nullable=True)
    google_new_reviews = Column(Integer, default=0)
    google_review_response = Column(String(20), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    store = relationship("Store")

    __table_args__ = (
        UniqueConstraint("store_id", "date"),
        Index("ix_tracker_store_date", "store_id", "date"),
    )


# ── MCP Daily Sales (synced from SmartService, all countries incl. India) ──
class McpDailySale(Base):
    __tablename__ = "mcp_daily_sales"
    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    date = Column(Date, nullable=False)
    revenue = Column(Numeric(14, 2), default=0)
    units_sold = Column(Integer, default=0)
    new_sale_count = Column(Integer, default=0)
    replacement_count = Column(Integer, default=0)
    return_count = Column(Integer, default=0)
    target = Column(Numeric(14, 2), default=0)
    currency = Column(String(10), default="")
    synced_at = Column(DateTime, default=datetime.utcnow)

    store = relationship("Store")

    __table_args__ = (
        UniqueConstraint("store_id", "date"),
        Index("ix_mcp_daily_sales_store_date", "store_id", "date"),
    )


# ── Country Sales Snapshot ───────────────────────────────────────────
# Saved once per sync from MCP's own country-comparison tool (which does
# its own USD conversion using current rates at that moment), so the
# International Sales chart can read a stored value instead of calling MCP
# on every dashboard load. Overwritten in place on each sync — this is a
# "latest known" snapshot per country, not a history.
class CountrySalesSnapshot(Base):
    __tablename__ = "country_sales_snapshots"
    country = Column(String(50), primary_key=True)
    local_amount = Column(Numeric(16, 2), default=0)
    local_currency = Column(String(10), default="")
    usd_amount = Column(Numeric(16, 2), default=0)
    synced_at = Column(DateTime, default=datetime.utcnow)


# ── Store Dashboard (from xlsx) ───────────────────────────────────
class StoreDashboardSnapshot(Base):
    __tablename__ = "store_dashboard_snapshots"
    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False)
    snapshot_date = Column(String(30), nullable=False)
    store_name = Column(String(100), nullable=False)
    country = Column(String(10), default="")
    mtd_revenue = Column(Numeric(14, 2), default=0)
    monthly_target = Column(Numeric(14, 2), default=0)
    target_pct = Column(Float, default=0)
    care_plus_pct = Column(Float, default=0)
    total_views = Column(Integer, default=0)
    engagements = Column(Integer, default=0)
    eng_rate_pct = Column(Float, default=0)
    prebookings = Column(Integer, default=0)
    dms_received = Column(Integer, default=0)
    wa_response_pct = Column(Float, default=0)
    walkins_booked = Column(Integer, default=0)
    insta_followers = Column(Integer, default=0)
    follower_growth = Column(Integer, default=0)
    google_rating = Column(Float, nullable=True)
    new_reviews = Column(Integer, default=0)
    sales_status = Column(String(50), default="")
    marketing_status = Column(String(50), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    store = relationship("Store")

    __table_args__ = (
        UniqueConstraint("store_id", "snapshot_date"),
    )


# ── AI Executive Summary ─────────────────────────────────────────
class AISummaryConfig(Base):
    __tablename__ = "ai_summary_config"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False, default="overview")
    system_prompt = Column(Text, default="")
    provider = Column(String(20), default="claude")
    model_name = Column(String(100), default="")
    is_active = Column(Boolean, default=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Tele Call Leads (from TL Google Sheets) ─────────────────────────
class TeleCallLead(Base):
    __tablename__ = "tele_call_leads"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sheet_tl_name = Column(String(100), nullable=False, index=True)
    person_calling = Column(String(100), default="")
    lead_source = Column(String(100), default="")
    created_time = Column(String(50), default="")
    full_name = Column(String(200), default="")
    phone = Column(String(30), default="")
    email = Column(String(200), default="")
    status = Column(String(50), default="")
    call_date = Column(String(30), default="")
    appointment_date = Column(String(30), default="")
    remarks = Column(Text, default="")
    sale_amount = Column(String(50), default="")
    product = Column(String(200), default="")
    salesperson = Column(String(100), default="")
    edited_by_user = Column(Boolean, default=False)
    spreadsheet_id = Column(String(200), default="")
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Telecalling CRM layer (migration 011) ──
    # App-owned fields. The sheet sync never writes these from sheet columns;
    # they are derived or set by people in the app. All nullable so existing
    # rows and the existing pages keep working untouched.
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    assigned_at = Column(DateTime, nullable=True)
    assignment_source = Column(String(20), nullable=True)  # sheet | auto | manual
    reassign_count = Column(Integer, default=0, nullable=True)
    submitted_at = Column(DateTime, nullable=True)  # parsed Meta "Created Time" (UTC)
    first_contact_at = Column(DateTime, nullable=True)
    last_contact_at = Column(DateTime, nullable=True)
    next_follow_up_at = Column(DateTime, nullable=True, index=True)
    is_urgent = Column(Boolean, default=False, nullable=True)
    escalated_at = Column(DateTime, nullable=True)
    stage = Column(String(30), nullable=True)
    stage_manual = Column(Boolean, default=False, nullable=True)
    priority = Column(String(10), nullable=True)  # hot | warm | cold
    priority_manual = Column(Boolean, default=False, nullable=True)
    phone_model = Column(String(100), nullable=True)
    service_type = Column(String(100), nullable=True)
    coverage = Column(String(50), nullable=True)
    potential_value = Column(Numeric(12, 2), nullable=True)
    sheet_status_raw = Column(String(100), nullable=True)
    # Names of fields changed in the app, so the sync never overwrites them.
    edited_fields = Column(JSON, nullable=True)

    owner = relationship("User", foreign_keys=[owner_user_id])

    __table_args__ = (
        Index("ix_tele_leads_tl_status", "sheet_tl_name", "status"),
        Index("ix_tele_leads_tl_stage", "sheet_tl_name", "stage"),
    )


# ── Tele Sheet Assignments (user → city sheet mapping) ─────────────
class TeleSheetAssignment(Base):
    __tablename__ = "tele_sheet_assignments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sheet_tl_name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("user_id", "sheet_tl_name"),
    )


# ── Telecalling CRM (migration 011) ────────────────────────────────
class TeleLeadActivity(Base):
    """Timeline entry for a tele call lead: calls, status/stage changes,
    assignments, notes. user_id NULL means the system did it."""
    __tablename__ = "tele_lead_activities"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("tele_call_leads.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    type = Column(String(30), nullable=False)
    outcome = Column(String(40), nullable=True)
    old_value = Column(String(200), nullable=True)
    new_value = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_tele_act_lead_time", "lead_id", "created_at"),
        Index("ix_tele_act_user_time", "user_id", "created_at"),
    )


class TeleLeadFollowup(Base):
    """A due action on a lead. owner_user_id is the owner AT THAT TIME and is
    never rewritten: a reassignment closes this row as 'reassigned' and opens
    a new one, so a missed deadline stays with the person who missed it."""
    __tablename__ = "tele_lead_followups"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("tele_call_leads.id", ondelete="CASCADE"), nullable=False)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    kind = Column(String(30), nullable=False, default="call")
    due_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    completed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    outcome = Column(String(40), nullable=True)
    status = Column(String(20), nullable=False, default="open")
    attempt_no = Column(Integer, default=1)
    reason = Column(String(200), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    lead = relationship("TeleCallLead", foreign_keys=[lead_id])
    owner = relationship("User", foreign_keys=[owner_user_id])

    __table_args__ = (
        Index("ix_tele_fu_owner_status_due", "owner_user_id", "status", "due_at"),
        Index("ix_tele_fu_lead_status", "lead_id", "status"),
    )


class TeleAppointment(Base):
    __tablename__ = "tele_appointments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("tele_call_leads.id", ondelete="CASCADE"), nullable=False)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True)
    scheduled_at = Column(DateTime, nullable=False)
    purpose = Column(String(200), nullable=True)
    attendance = Column(String(20), nullable=False, default="scheduled")
    source = Column(String(10), nullable=False, default="app")  # app | sheet
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    lead = relationship("TeleCallLead", foreign_keys=[lead_id])
    store = relationship("Store", foreign_keys=[store_id])

    __table_args__ = (
        Index("ix_tele_appt_time", "scheduled_at"),
    )


class CrmAlert(Base):
    """Operational alert for one recipient. Acknowledging does not resolve;
    resolved_at is set when the underlying follow-up is handled."""
    __tablename__ = "crm_alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("tele_call_leads.id", ondelete="CASCADE"), nullable=True)
    followup_id = Column(Integer, ForeignKey("tele_lead_followups.id", ondelete="SET NULL"), nullable=True)
    recipient_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String(40), nullable=False)
    level = Column(Integer, default=1)  # 1 owner, 2 team leader, 3 admin
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    dedupe_key = Column(String(150), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_crm_alert_recipient", "recipient_user_id", "resolved_at"),
    )


class PriceBookEntry(Base):
    """One price for phone model + service + coverage. price NULL means the
    rate still needs review."""
    __tablename__ = "price_book_entries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_model = Column(String(100), nullable=False)
    service_type = Column(String(100), nullable=False)
    coverage = Column(String(50), nullable=False, default="Standard")
    price = Column(Numeric(12, 2), nullable=True)
    is_active = Column(Boolean, default=True)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("phone_model", "service_type", "coverage", name="uq_price_book_entry"),
    )


class CrmSavedView(Base):
    __tablename__ = "crm_saved_views"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    page = Column(String(50), nullable=False, default="leads")
    name = Column(String(100), nullable=False)
    filters = Column(JSON, nullable=True)
    columns = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AISummaryRun(Base):
    __tablename__ = "ai_summary_run"
    id = Column(Integer, primary_key=True, autoincrement=True)
    config_id = Column(Integer, ForeignKey("ai_summary_config.id"), nullable=True)
    period = Column(String(7), nullable=False)  # "2026-08"
    input_fingerprint = Column(String(200), default="")
    status = Column(String(20), default="ok")  # ok, error, running
    response_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    provider = Column(String(20), default="claude")
    model = Column(String(100), default="")
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost_estimate = Column(Numeric(10, 6), default=0)
    generated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    config = relationship("AISummaryConfig")

    __table_args__ = (
        Index("ix_summary_run_period", "period"),
    )
