import logging
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from slowapi.errors import RateLimitExceeded

from config import get_settings
from inference import init_model
from limiter import limiter                          # ← single shared instance
from routes.auth_routes import router as auth_router
from routes.feedback_routes import router as feedback_router
from routes.health_routes import router as health_router
from routes.monitoring_routes import router as monitoring_router
from routes.predict_routes import router as predict_router
from routes.stats_routes import router as stats_router

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger   = logging.getLogger(__name__)
settings = get_settings()

# ── Sentry (opt-in) ───────────────────────────────────────────────────────────
if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_env,
        release=f"smartbin-api@{settings.app_version}",
        traces_sample_rate=0.2 if settings.sentry_env == "production" else 1.0,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
        send_default_pii=False,   # never send auth headers or file contents
    )
    logger.info("Sentry initialised (env=%s)", settings.sentry_env)
else:
    logger.info("SENTRY_DSN not set — Sentry disabled")


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading ONNX model...")
    init_model(settings.onnx_model_path)
    logger.info("Model ready. SmartBin API started.")
    yield
    logger.info("SmartBin API shutting down.")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="SmartBin API",
    version=settings.app_version,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.state.limiter = limiter


# ── Graceful 429 handler ──────────────────────────────────────────────────────
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Return JSON on 429. Retry-After header is added by slowapi (headers_enabled=True).
    OWASP A05: keep message generic — do not leak internal rate-limit detail.
    """
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please slow down and try again shortly."},
        headers={"Retry-After": str(getattr(exc, "retry_after", 60))},
    )


# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)

# ── Trusted hosts ─────────────────────────────────────────────────────────────
trusted_hosts = [settings.trusted_host, "localhost", "127.0.0.1"]
if settings.debug:
    trusted_hosts.append("*")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)


# ── Security headers ──────────────────────────────────────────────────────────
@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:
    response: Response = await call_next(request)
    response.headers["X-Frame-Options"]           = "DENY"
    response.headers["X-Content-Type-Options"]    = "nosniff"
    response.headers["X-XSS-Protection"]          = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"]   = "default-src 'none'; frame-ancestors 'none'"
    if "server" in response.headers:
        del response.headers["server"]
    return response


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(predict_router)
app.include_router(feedback_router)
app.include_router(stats_router)
app.include_router(health_router)
app.include_router(monitoring_router)
