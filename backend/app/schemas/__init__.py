from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime, date


# ── Auth ───────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PasswordResetRequest(BaseModel):
    email: str


class SetPasswordRequest(BaseModel):
    token: str
    new_password: str


# ── User ───────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role_id: int
    is_active: bool = True
    store_ids: List[int] = []  # Regional Manager: explicit multi-store grant
    store_id: Optional[int] = None  # Telecaller/Salesperson: single store
    team_leader_id: Optional[int] = None  # Telecaller/Salesperson: reports to


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role_id: Optional[int] = None
    is_active: Optional[bool] = None
    store_ids: Optional[List[int]] = None
    store_id: Optional[int] = None
    team_leader_id: Optional[int] = None


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role_id: int
    role_name: str = ""
    is_active: bool
    store_ids: List[int] = []
    store_id: Optional[int] = None
    team_leader_id: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ResetPasswordRequest(BaseModel):
    new_password: str


class UserMeResponse(BaseModel):
    id: int
    name: str
    email: str
    role_id: int
    role_name: str
    is_active: bool
    permissions: List[dict] = []
    store_ids: List[int] = []


# ── Role ───────────────────────────────────────────────────────────
class RoleCreate(BaseModel):
    name: str
    description: str = ""


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class RoleResponse(BaseModel):
    id: int
    name: str
    description: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PermissionResponse(BaseModel):
    id: int
    resource: str
    action: str

    class Config:
        from_attributes = True


class RolePermissionUpdate(BaseModel):
    permission_ids: List[int]


# ── Store ──────────────────────────────────────────────────────────
class StoreCreate(BaseModel):
    name: str
    team_leader_id: int
    currency_code: str = "INR"
    daily_target: float = 0
    monthly_target: float = 0
    breakeven_revenue: float = 0
    profitability_target: float = 0
    fixed_costs: float = 0
    variable_cost_pct: float = 0
    is_active: bool = True
    region: str = ""


class StoreUpdate(BaseModel):
    name: Optional[str] = None
    team_leader_id: Optional[int] = None
    currency_code: Optional[str] = None
    daily_target: Optional[float] = None
    monthly_target: Optional[float] = None
    breakeven_revenue: Optional[float] = None
    profitability_target: Optional[float] = None
    fixed_costs: Optional[float] = None
    variable_cost_pct: Optional[float] = None
    is_active: Optional[bool] = None
    region: Optional[str] = None
    address: Optional[str] = None
    maps_link: Optional[str] = None
    needs_review: Optional[bool] = None


class StoreResponse(BaseModel):
    id: int
    name: str
    team_leader_id: int
    team_leader_name: str = ""
    currency_code: str
    daily_target: float
    monthly_target: float
    breakeven_revenue: float
    profitability_target: float
    fixed_costs: float
    variable_cost_pct: float
    is_active: bool
    region: str
    address: str = ""
    maps_link: str = ""
    country: str = "India"
    needs_review: bool = False
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Daily Submission ───────────────────────────────────────────────
class DailySubmissionCreate(BaseModel):
    store_id: int
    date: date
    revenue: float = 0
    units_sold: int = 0
    care_plus_attached: int = 0
    new_leads: int = 0
    active_leads: int = 0
    calls_made: int = 0
    calls_connected: int = 0
    walk_ins: int = 0
    walk_in_conversions: int = 0
    staff_on_duty: int = 0
    training_done: bool = False
    training_topic: str = ""
    stock_opening: int = 0
    stock_received: int = 0
    stock_sold: int = 0
    stock_closing: int = 0
    stock_variance: int = 0
    cash_opening: float = 0
    cash_sales: float = 0
    bank_deposit: float = 0
    petty_cash_note: str = ""
    cash_closing: float = 0
    installations: int = 0
    service_calls: int = 0
    complaints_in: int = 0
    complaints_resolved: int = 0
    app_updated: bool = False
    notes: str = ""
    google_review_rating: Optional[float] = None


class DailySubmissionUpdate(BaseModel):
    revenue: Optional[float] = None
    units_sold: Optional[int] = None
    care_plus_attached: Optional[int] = None
    new_leads: Optional[int] = None
    active_leads: Optional[int] = None
    calls_made: Optional[int] = None
    calls_connected: Optional[int] = None
    walk_ins: Optional[int] = None
    walk_in_conversions: Optional[int] = None
    staff_on_duty: Optional[int] = None
    training_done: Optional[bool] = None
    training_topic: Optional[str] = None
    stock_opening: Optional[int] = None
    stock_received: Optional[int] = None
    stock_sold: Optional[int] = None
    stock_closing: Optional[int] = None
    stock_variance: Optional[int] = None
    cash_opening: Optional[float] = None
    cash_sales: Optional[float] = None
    bank_deposit: Optional[float] = None
    petty_cash_note: Optional[str] = None
    cash_closing: Optional[float] = None
    installations: Optional[int] = None
    service_calls: Optional[int] = None
    complaints_in: Optional[int] = None
    complaints_resolved: Optional[int] = None
    app_updated: Optional[bool] = None
    notes: Optional[str] = None
    google_review_rating: Optional[float] = None


class DailySubmissionResponse(BaseModel):
    id: int
    store_id: int
    store_name: str = ""
    date: date
    revenue: float
    units_sold: int
    care_plus_attached: int
    new_leads: int
    active_leads: int
    calls_made: int
    calls_connected: int
    walk_ins: int
    walk_in_conversions: int
    staff_on_duty: int
    training_done: bool
    training_topic: str
    stock_opening: int
    stock_received: int
    stock_sold: int
    stock_closing: int
    stock_variance: int
    cash_opening: float
    cash_sales: float
    bank_deposit: float
    petty_cash_note: str
    cash_closing: float
    installations: int
    service_calls: int
    complaints_in: int
    complaints_resolved: int
    app_updated: bool
    notes: str
    google_review_rating: Optional[float]
    submitted_by: Optional[int]
    submitted_at: Optional[datetime]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Lead ───────────────────────────────────────────────────────────
class LeadCreate(BaseModel):
    store_id: int
    source: str = "inbound"
    name: str
    phone: str = ""
    status: str = "warm"
    stage: str = "new"
    assigned_to: Optional[int] = None


class LeadUpdate(BaseModel):
    store_id: Optional[int] = None
    source: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    stage: Optional[str] = None
    assigned_to: Optional[int] = None


class LeadResponse(BaseModel):
    id: int
    store_id: int
    store_name: str = ""
    source: str
    name: str
    phone: str
    status: str
    stage: str
    assigned_to: Optional[int]
    assignee_name: str = ""
    created_at: Optional[datetime]
    last_contacted_at: Optional[datetime]

    class Config:
        from_attributes = True


class LeadActivityCreate(BaseModel):
    lead_id: int
    type: str
    outcome: str = ""
    notes: str = ""


class LeadActivityResponse(BaseModel):
    id: int
    lead_id: int
    type: str
    outcome: str
    notes: str
    created_by: Optional[int]
    creator_name: str = ""
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class LostReasonCreate(BaseModel):
    store_id: int
    date: date
    reason: str
    count: int = 1


class LostReasonResponse(BaseModel):
    id: int
    store_id: int
    date: date
    reason: str
    count: int
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Campaign ───────────────────────────────────────────────────────
class CampaignCreate(BaseModel):
    name: str
    channel: str = ""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: float = 0
    status: str = "draft"
    success_rate: float = 0


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    channel: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = None
    status: Optional[str] = None
    success_rate: Optional[float] = None


class CampaignResponse(BaseModel):
    id: int
    name: str
    channel: str
    start_date: Optional[date]
    end_date: Optional[date]
    budget: float
    status: str
    success_rate: float
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Task ───────────────────────────────────────────────────────────
class TaskCreate(BaseModel):
    title: str
    description: str = ""
    type: str = "task"
    assigned_to: Optional[int] = None
    store_id: Optional[int] = None
    due_at: Optional[datetime] = None
    status: str = "pending"
    priority: str = "medium"


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    assigned_to: Optional[int] = None
    store_id: Optional[int] = None
    due_at: Optional[datetime] = None
    status: Optional[str] = None
    priority: Optional[str] = None


class TaskResponse(BaseModel):
    id: int
    title: str
    description: str
    type: str
    assigned_to: Optional[int]
    assignee_name: str = ""
    store_id: Optional[int]
    store_name: str = ""
    due_at: Optional[datetime]
    status: str
    priority: str
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Investment ─────────────────────────────────────────────────────
class InvestmentCreate(BaseModel):
    store_id: Optional[int] = None
    category: str
    description: str = ""
    amount: float
    date: date


class InvestmentUpdate(BaseModel):
    store_id: Optional[int] = None
    category: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[date] = None


class InvestmentResponse(BaseModel):
    id: int
    store_id: Optional[int]
    store_name: str = ""
    category: str
    description: str
    amount: float
    date: date
    created_by: Optional[int]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── KPI / Performance ──────────────────────────────────────────────
class KPIWeightUpdate(BaseModel):
    kpi_name: str
    weight: float


class KPIWeightsBulkUpdate(BaseModel):
    weights: List[KPIWeightUpdate]


class KPIWeightResponse(BaseModel):
    id: int
    kpi_name: str
    description: str
    weight: float

    class Config:
        from_attributes = True


class IncentiveBandCreate(BaseModel):
    band_name: str
    min_kpi_score: float
    multiplier: float
    label: str


class IncentiveBandUpdate(BaseModel):
    band_name: Optional[str] = None
    min_kpi_score: Optional[float] = None
    multiplier: Optional[float] = None
    label: Optional[str] = None


class IncentiveBandResponse(BaseModel):
    id: int
    band_name: str
    min_kpi_score: float
    multiplier: float
    label: str

    class Config:
        from_attributes = True


class KPIScoreResponse(BaseModel):
    store_id: int
    store_name: str
    period_start: date
    period_end: date
    scores: dict = {}
    total_score: float = 0
    incentive_band: str = ""
    incentive_multiplier: float = 1.0


# ── Google Review ──────────────────────────────────────────────────
class GoogleReviewCreate(BaseModel):
    store_id: int
    date: date
    rating: float = 0
    total_reviews: int = 0
    new_reviews: int = 0


class GoogleReviewResponse(BaseModel):
    id: int
    store_id: int
    date: date
    rating: float
    total_reviews: int
    new_reviews: int
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Currency ───────────────────────────────────────────────────────
class CurrencyResponse(BaseModel):
    code: str
    name: str
    symbol: str
    decimal_places: int
    number_format_style: str

    class Config:
        from_attributes = True


class ExchangeRateCreate(BaseModel):
    currency_code: str
    rate_to_base: float
    effective_date: date


class ExchangeRateResponse(BaseModel):
    id: int
    currency_code: str
    rate_to_base: float
    effective_date: date
    source: str
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Sheet Sync ─────────────────────────────────────────────────────
class SheetSourceCreate(BaseModel):
    label: str
    spreadsheet_id: str
    is_xlsx_upload: bool = False
    sync_interval_minutes: int = 5
    is_enabled: bool = True
    tab_mappings: dict = {}


class SheetSourceUpdate(BaseModel):
    label: Optional[str] = None
    spreadsheet_id: Optional[str] = None
    is_xlsx_upload: Optional[bool] = None
    sync_interval_minutes: Optional[int] = None
    is_enabled: Optional[bool] = None
    tab_mappings: Optional[dict] = None


class SheetSourceResponse(BaseModel):
    id: int
    label: str
    spreadsheet_id: str
    is_xlsx_upload: bool
    sync_interval_minutes: int
    is_enabled: bool
    tab_mappings: dict
    last_synced_at: Optional[datetime] = None
    last_sync_status: str = ""
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class SheetSyncLogResponse(BaseModel):
    id: int
    sheet_source_id: int
    tab_name: str
    last_synced_at: Optional[datetime]
    rows_synced: int
    status: str
    error_message: str
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Settings ───────────────────────────────────────────────────────
class SettingUpdate(BaseModel):
    key: str
    value: str


class SettingResponse(BaseModel):
    key: str
    value: str
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Dashboard ──────────────────────────────────────────────────────
class KPICard(BaseModel):
    value: float
    delta: float = 0
    trend: List[float] = []


class DashboardResponse(BaseModel):
    total_revenue: KPICard
    total_target: KPICard
    achievement_pct: KPICard
    total_investment: KPICard
    active_team_leaders: KPICard
    active_leads: KPICard
    revenue_trend: List[dict] = []
    revenue_breakdown: List[dict] = []
    achievement_gauge: float = 0
    top_team_leaders: List[dict] = []
    lead_status_distribution: List[dict] = []
    bottom_strip: dict = {}


# ── CEO Dashboard Schemas ──────────────────────────────────────────
class MarketingMetricsCreate(BaseModel):
    store_id: int
    month: str
    ig_videos_posted: Optional[int] = None
    ig_views: Optional[int] = None
    ig_followers: Optional[int] = None
    ig_new_followers: Optional[int] = None
    ig_likes: Optional[int] = None
    ig_comments: Optional[int] = None
    ig_dms_received: Optional[int] = None
    ig_manychat_handled: Optional[int] = None
    ig_posts: Optional[int] = None
    wa_walkins: int = 0
    google_rating: Optional[float] = None
    google_new_reviews: Optional[int] = None
    google_review_response: str = ""


class MarketingMetricsResponse(BaseModel):
    id: int
    store_id: int
    store_name: str = ""
    month: str
    ig_videos_posted: Optional[int]
    ig_views: Optional[int]
    ig_followers: Optional[int]
    ig_new_followers: Optional[int]
    ig_likes: Optional[int]
    ig_comments: Optional[int]
    ig_dms_received: Optional[int]
    ig_manychat_handled: Optional[int]
    ig_posts: Optional[int]
    wa_walkins: int
    google_rating: Optional[float]
    google_new_reviews: Optional[int]
    google_review_response: str

    class Config:
        from_attributes = True


class StoreStaffCreate(BaseModel):
    store_id: int
    month: str
    manager_name: str = ""
    staff_count: int = 0
    total_headcount: int = 0
    has_accommodation: bool = False
    resignation_risk: int = 0
    training_active: bool = False
    notes: str = ""


class StoreStaffResponse(BaseModel):
    id: int
    store_id: int
    store_name: str = ""
    month: str
    manager_name: str
    staff_count: int
    total_headcount: int
    has_accommodation: bool
    resignation_risk: int
    training_active: bool
    notes: str

    class Config:
        from_attributes = True


class InternationalStoreCreate(BaseModel):
    name: str
    country: str
    region: str
    month: str
    target: Optional[float] = None
    actual: float = 0


class InternationalStoreResponse(BaseModel):
    id: int
    name: str
    country: str
    region: str
    month: str
    target: Optional[float]
    actual: float

    class Config:
        from_attributes = True


class StrategicInsightCreate(BaseModel):
    month: str
    category: str
    title: str
    description: str = ""
    action_tag: str = ""
    assigned_to: str = ""
    section: str = "overview"
    priority: str = "high"
    deadline: str = ""
    sort_order: int = 0


class StrategicInsightResponse(BaseModel):
    id: int
    month: str
    category: str
    title: str
    description: str
    action_tag: str
    assigned_to: str
    section: str
    priority: str
    deadline: str
    sort_order: int

    class Config:
        from_attributes = True


class BulkImportRequest(BaseModel):
    month: str
    data: List[dict]


class CEOOverviewResponse(BaseModel):
    kpis: dict = {}
    store_achievements: List[dict] = []
    tl_achievements: List[dict] = []
    rag_distribution: dict = {}
    intl_overview: List[dict] = []
    wa_walkins_top: List[dict] = []
    insights: List[dict] = []


class CEOOpsResponse(BaseModel):
    kpis: dict = {}
    store_table: List[dict] = []
    insights: List[dict] = []


class CEOTLResponse(BaseModel):
    kpis: dict = {}
    tl_cards: List[dict] = []
    tl_stores: List[dict] = []
    insights: List[dict] = []


class CEOIntlResponse(BaseModel):
    country_cards: List[dict] = []
    stores: List[dict] = []
    insights: List[dict] = []


class CEOMarketingResponse(BaseModel):
    kpis: dict = {}
    store_table: List[dict] = []
    insights: List[dict] = []


class CEOReviewsResponse(BaseModel):
    kpis: dict = {}
    store_table: List[dict] = []
    insights: List[dict] = []


class CEOPeopleResponse(BaseModel):
    kpis: dict = {}
    store_table: List[dict] = []


class CEOActionsResponse(BaseModel):
    critical: List[dict] = []
    high: List[dict] = []
    strategic: List[dict] = []
