from fastapi import APIRouter

from app.api.routes.analytics import router as analytics_router
from app.api.routes.artifacts import router as artifacts_router
from app.api.routes.attachments import router as attachments_router
from app.api.routes.browser import router as browser_router
from app.api.routes.builder import router as builder_router
from app.api.routes.auth import router as auth_router
from app.api.routes.chats import router as chats_router
from app.api.routes.completions import router as completions_router
from app.api.routes.connectors import router as connectors_router
from app.api.routes.earnings import router as earnings_router
from app.api.routes.health import router as health_router
from app.api.routes.keys import router as keys_router
from app.api.routes.media import router as media_router
from app.api.routes.pay import router as pay_router
from app.api.routes.search import router as search_router
from app.api.routes.tools import router as tools_router
from app.api.routes.waitlist import router as waitlist_router
from app.api.routes.admin import router as admin_router
from app.api.routes.wallet import router as wallet_router
from app.api.routes.webhooks import router as webhooks_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(analytics_router)
api_router.include_router(auth_router)
api_router.include_router(keys_router)
api_router.include_router(chats_router)
api_router.include_router(completions_router)
api_router.include_router(attachments_router)
api_router.include_router(artifacts_router)
api_router.include_router(browser_router)
api_router.include_router(connectors_router)
api_router.include_router(search_router)
api_router.include_router(media_router)
api_router.include_router(tools_router)
api_router.include_router(builder_router)
api_router.include_router(waitlist_router)
api_router.include_router(wallet_router)
api_router.include_router(webhooks_router)
api_router.include_router(pay_router)
api_router.include_router(earnings_router)
api_router.include_router(admin_router)
