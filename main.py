import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config import get_settings
from inference import init_model
from routes.auth_routes import router as auth_router
from routes.predict_routes import router as predict_router
from routes.feedback_routes import router as feedback_router
from routes.stats_routes import router as stats_router
from routes.health_routes import router as health_router

# ── Logging setup ─────────────────────────────────────────────────────────────
# Show only WARNING+ for noisy third-party libraries
# Keep INFO for our own app code
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)       # silences Supabase HTTP logs
logging.getLogger("httpcore").setLevel(logging.WARNING)    # silences underlying HTTP core
logging.getLogger("hpack").setLevel(logging.WARNING)       # silences HTTP/2 header logs
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # suppress per-request access logs
                                                               # (we log errors ourselves)

logger   = logging.getLogger(__name__)
settings = get_settings()

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


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
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)

# Trusted hosts — include Render internal IPs and health check ranges
trusted_hosts = [
    "smartbin-api-96u6.onrender.com",  # your actual Render hostname
    "smartbin-api.onrender.com",
    "localhost",
    "127.0.0.1",
    "10.*",       # Render internal health check IPs
    "3.*",        # AWS health check IPs (UptimeRobot)
    "34.*",       # AWS/UptimeRobot
    "52.*",
]
if settings.debug:
    trusted_hosts = ["*"]

app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)


# ── Security headers ──────────────────────────────────────────────────────────
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Frame-Options"]           = "DENY"
    response.headers["X-Content-Type-Options"]    = "nosniff"
    response.headers["X-XSS-Protection"]          = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"]   = "default-src 'none'; frame-ancestors 'none'"
    response.headers.pop("server", None)
    return response


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(predict_router)
app.include_router(feedback_router)
app.include_router(stats_router)
app.include_router(health_router)
