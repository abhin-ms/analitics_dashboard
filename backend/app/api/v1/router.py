from fastapi import APIRouter
from .auth import router as auth_router
from .users import router as users_router
from .roles import router as roles_router
from .stores import router as stores_router
from .daily_submissions import router as submissions_router
from .leads import router as leads_router
from .campaigns import router as campaigns_router
from .tasks import router as tasks_router
from .investments import router as investments_router
from .dashboard import router as dashboard_router
from .settings import router as settings_router
from .sync import router as sync_router
from .currencies import router as currencies_router
from .performance import router as performance_router
from .reports import router as reports_router
from .ceo_dashboard import router as ceo_router
from .ai_analytics import router as ai_analytics_router
from .mcp_reports import router as mcp_reports_router
from .sales_reports import router as sales_reports_router
from .client_logs import router as client_logs_router
from .tele_call_leads import router as tele_call_leads_router
from .crm import router as crm_router
from .crm_admin import router as crm_admin_router
from ...instagram.router import router as instagram_router
from ...instagram.webhook_handler import router as instagram_webhook_router
from ...instagram.form_router import router as instagram_form_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(roles_router)
api_router.include_router(stores_router)
api_router.include_router(submissions_router)
api_router.include_router(leads_router)
api_router.include_router(campaigns_router)
api_router.include_router(tasks_router)
api_router.include_router(investments_router)
api_router.include_router(dashboard_router)
api_router.include_router(settings_router)
api_router.include_router(sync_router)
api_router.include_router(currencies_router)
api_router.include_router(performance_router)
api_router.include_router(reports_router)
api_router.include_router(ceo_router)
api_router.include_router(ai_analytics_router)
api_router.include_router(mcp_reports_router)
api_router.include_router(sales_reports_router)
api_router.include_router(client_logs_router)
api_router.include_router(tele_call_leads_router)
api_router.include_router(crm_router)
api_router.include_router(crm_admin_router)
api_router.include_router(instagram_webhook_router)
api_router.include_router(instagram_router)
api_router.include_router(instagram_form_router)
