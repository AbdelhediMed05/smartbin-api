<p align="center">
  <img src="https://img.shields.io/badge/SmartBin-API-22c55e?style=flat-square" />
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/ONNX%20Runtime-1.24-gray?style=flat-square" />
  <img src="https://img.shields.io/badge/deployed%20on-Render-46E3B7?style=flat-square&logo=render&logoColor=white" />
</p>

<h1 align="center">SmartBin — API</h1>

<p align="center">
  FastAPI backend powering the SmartBin waste-classification system.<br/>
  Runs a YOLO ONNX model to detect <strong>Plastic · Glass · Metal · Paper</strong> in uploaded images.
</p>

---

## Overview

SmartBin API is the backend of the SmartBin system. It exposes a REST API consumed by the [SmartBin App](https://github.com/AbdelhediMed05/smartbin-app) that:

- Accepts image uploads and runs **YOLO object-detection inference** via an ONNX model to classify waste items
- Manages **user accounts and JWT authentication** backed by Supabase
- Persists **prediction results and user feedback** (corrections with optional bounding boxes) to Supabase
- Exposes **stats and a leaderboard** based on user contributions
- Collects **frontend errors** and forwards them to Sentry for end-to-end observability
- Applies layered **OWASP-aligned security controls**: rate limiting, input validation, magic-byte MIME checks, EXIF stripping, security headers, and IP hashing

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.11 |
| Framework | FastAPI 0.111 + Uvicorn |
| ML Inference | ONNX Runtime 1.24 (CPU) |
| Model | Custom-trained YOLO (exported to `.onnx`) |
| Database / Auth | Supabase (PostgreSQL + Auth) |
| Image processing | Pillow |
| Validation | Pydantic v2 |
| Rate limiting | SlowAPI |
| Auth tokens | python-jose (JWT) |
| Error monitoring | Sentry SDK (FastAPI + Starlette integrations) |
| Deployment | Render (Python web service) |
| Testing | Pytest |

---

## Project Structure

```
smartbin-api/
├── main.py                         # App factory: middleware, routers, lifespan
├── config.py                       # Pydantic Settings (reads from .env)
├── auth.py                         # JWT token verification dependency
├── inference.py                    # ONNX model wrapper (letterbox, pre/post-process)
├── security.py                     # validate_image, strip_exif, hash_ip, sanitize_filename
├── validators.py                   # Annotated field types (email, password, bbox coords…)
├── limiter.py                      # SlowAPI limiter singleton + user+IP key function
├── request_limits.py               # Per-route request-body size enforcement
├── request_models.py               # Base Pydantic model with extra="forbid"
├── db.py                           # Supabase client initialisation
├── best_combined.onnx              # Trained YOLO model weights
├── requirements.txt
├── runtime.txt                     # Python 3.11.9
├── render.yaml                     # Render deployment manifest
├── pyproject.toml                  # Pytest and Ruff configuration
│
├── domain/
│   ├── classes.py                  # CLASS_NAMES, CLASS_COLORS, CLASS_IDS
│   └── auth_policy.py              # Password and username rules
│
├── routes/
│   ├── auth_routes.py              # POST /auth/register|login|refresh|logout
│   ├── predict_routes.py           # POST /predict, DELETE /predict/{id}/cancel
│   ├── feedback_routes.py          # POST /feedback/{prediction_id}
│   ├── stats_routes.py             # GET /stats/me, GET /stats/leaderboard
│   ├── health_routes.py            # GET /health
│   └── monitoring_routes.py        # POST /monitoring/frontend-error
│
├── services/
│   ├── auth_service.py             # Register, login, refresh, logout business logic
│   ├── predict_service.py          # Image validation → inference → DB persist
│   ├── feedback_service.py         # Feedback persist + HuggingFace dataset upload
│   ├── stats_service.py            # Leaderboard and personal stats queries
│   └── monitoring_service.py       # Text scrubbing before Sentry capture
│
├── repositories/
│   ├── prediction_repository.py    # Supabase CRUD for predictions
│   ├── auth_repository.py          # Supabase auth wrappers
│   └── stats_repository.py         # Supabase stats queries
│
└── tests/
    ├── test_domain.py
    ├── test_inference.py
    ├── test_monitoring_service.py
    ├── test_request_limits.py
    ├── test_security.py
    └── test_validators.py
```

---

## Getting Started

### Prerequisites

- Python 3.11
- A [Supabase](https://supabase.com) project (database + auth)
- _(Optional)_ A [Sentry](https://sentry.io) project for error tracking
- _(Optional)_ A [HuggingFace](https://huggingface.co) dataset repo for feedback storage

### Installation

```bash
# Clone the repository
git clone https://github.com/AbdelhediMed05/smartbin-api.git
cd smartbin-api

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file at the root of the project:

```env
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_KEY=your_service_role_key

# JWT (must match your Supabase JWT secret)
JWT_SECRET=your_jwt_secret

# ONNX model
ONNX_MODEL_PATH=best_combined.onnx
CONFIDENCE_THRESHOLD=0.45
IOU_THRESHOLD=0.45
MAX_IMAGE_SIZE_MB=10

# CORS / Trusted hosts
FRONTEND_URL=http://localhost:5500
TRUSTED_HOST=localhost

# App
DEBUG=true
APP_VERSION=1.0.0

# HuggingFace (feedback dataset upload — optional)
HF_TOKEN=your_hf_token
HF_DATASET_REPO=your_username/your-dataset

# Sentry (optional — leave empty to disable)
SENTRY_DSN=
SENTRY_ENV=development
```

> ⚠️ Never commit `.env`. It is already in `.gitignore`.

### Running the Server

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API is available at `http://localhost:8000`.

### Running Tests

```bash
pytest
```

---

## API Reference

All endpoints return JSON. Protected endpoints (🔒) require an `Authorization: Bearer <access_token>` header.

### Auth — `/auth`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/auth/register` | — | Create an account (`email`, `password`, `username`) |
| `POST` | `/auth/login` | — | Login; returns `access_token` + `refresh_token` |
| `POST` | `/auth/refresh` | — | Exchange a refresh token for a new access token |
| `POST` | `/auth/logout` | 🔒 | Invalidate the current session |

Rate limits: register `3/min`, login `5/min`, refresh `10/min`, logout `20/min` (all per IP).

### Prediction — `/predict`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/predict` | 🔒 | Upload an image (`multipart/form-data`); returns detections |
| `DELETE` | `/predict/{prediction_id}/cancel` | 🔒 | Cancel a pending prediction and clean up storage |

**Request** (`POST /predict`):
```
Content-Type: multipart/form-data
file: <image file>        (JPEG / PNG / WebP, ≤ MAX_IMAGE_SIZE_MB)
conf: 0.45                (float, 0.1 – 0.9, optional)
```

**Response**:
```json
{
  "prediction_id": "550e8400-e29b-41d4-a716-446655440000",
  "detections": [
    {
      "class": "Plastic",
      "class_id": 0,
      "confidence": 0.8712,
      "bbox": { "x1": 42, "y1": 18, "x2": 310, "y2": 290 },
      "color": "#1E90FF"
    }
  ],
  "inference_ms": 87,
  "image_size": { "width": 640, "height": 480 }
}
```

Rate limit: `10/min` per user+IP.

### Feedback — `/feedback`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/feedback/{prediction_id}` | 🔒 | Submit a correction for a prediction |

**Request body**:
```json
{
  "correct_class": "Glass",
  "was_correct": false,
  "bbox": { "x1": 50, "y1": 20, "x2": 300, "y2": 280 }
}
```

`correct_class` must be one of: `Plastic`, `Glass`, `Metal`, `Paper`, `Unknown`.  
`bbox` is optional. Rate limit: `15/min` per user+IP.

### Stats — `/stats`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/stats/me` | 🔒 | Personal prediction and feedback stats |
| `GET` | `/stats/leaderboard` | — | Top contributors by feedback count |

### Health & Monitoring

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | — | Returns API version and model status |
| `POST` | `/monitoring/frontend-error` | — | Ingests frontend errors and forwards to Sentry |

---

## ML Model

The inference pipeline uses a **YOLO model exported to ONNX** (`best_combined.onnx`), loaded once at startup as a singleton via `inference.py`.

**Classes:** `Plastic` · `Glass` · `Metal` · `Paper`

**Preprocessing pipeline:**
1. Convert to RGB
2. Letterbox-resize to 480 × 480 (preserving aspect ratio, padding with grey)
3. Normalise to `[0, 1]` and transpose to `(1, 3, H, W)`

**Postprocessing:**
- Filter detections by confidence threshold
- Remap bounding-box coordinates back to original image space (accounting for letterbox padding and scale)

---

## Security

The API follows OWASP Top-10 guidelines:

| Control | Implementation |
|---------|---------------|
| Input validation | Pydantic v2 with `extra="forbid"` on all request models; annotated field types enforce length and format bounds |
| File validation | Magic-byte MIME check (`python-magic`) + PIL `verify()` before inference |
| EXIF stripping | Pillow strips metadata from uploaded images before processing |
| Rate limiting | SlowAPI per-IP and per-user+IP buckets on every endpoint |
| Auth | JWT tokens verified on every protected request; refresh tokens enable silent renewal |
| IP privacy | Client IPs are one-way hashed before storage (`hash_ip`) |
| Security headers | `X-Frame-Options`, `X-Content-Type-Options`, `X-XSS-Protection`, `HSTS`, `CSP`, server header removed |
| CORS | Restricted to `FRONTEND_URL` only |
| Trusted hosts | `TrustedHostMiddleware` with explicit allowlist |
| Error leakage | Generic error messages on 429 and 500; internal details go to Sentry only |

---

## Deployment on Render

The repository includes a `render.yaml` manifest for one-click deployment.

### 1. Connect the repository to Render

Create a new **Web Service** on [render.com](https://render.com) and connect this repository.

### 2. Set environment variables

Add all variables from the [Environment Variables](#environment-variables) section in the Render dashboard (omit `DEBUG=true` in production and set `DEBUG=false`).

### 3. Deploy

Render runs:
```bash
pip install -r requirements.txt          # build
uvicorn main:app --host 0.0.0.0 --port $PORT  # start
```

A 1 GB persistent disk is mounted at `/opt/render/project/src` to store the ONNX model file between deploys.

---

## CI Pipeline

The repository uses **GitHub Actions** (`.github/workflows/ci.yml`).

### Triggers

| Event | Branches |
|-------|----------|
| `push` | `main`, `dev` |
| `pull_request` | `main` |

### Jobs

```
lint ──► test ──► auto-merge (dev → main, on push to dev only)
```

#### `Lint`

Runs `ruff check .` against the full codebase. The pipeline fails fast here — `test` will not run if linting fails.

#### `Test`

| Step | What it does |
|------|-------------|
| Checkout | Fetches the repository |
| Install system deps | Installs `libmagic1` (required by `python-magic` for MIME validation) |
| Install Python deps | `pip install -r requirements.txt` + `pytest pytest-cov` |
| Run tests | `pytest --tb=short -q` across all files in `tests/` |

`PYTHONPATH` is set to the workspace root so all local imports resolve correctly during testing.

#### `Merge dev → main` _(conditional)_

Runs only on a **push to `dev`** after `test` passes. Automatically merges `dev` into `main` with a no-fast-forward commit:

```
ci: auto-merge dev → main [tests passed]
```

### Required Secrets

No additional secrets are needed for CI — the test suite is designed to run without real Supabase or Sentry credentials.
