import uuid as _uuid
from typing import Annotated

from fastapi import HTTPException, Path
from pydantic import Field

# ── String field limits ───────────────────────────────────────────────────────

# OWASP recommendation: truncate before hashing to prevent long-password DoS.
# Supabase/GoTrue uses bcrypt (72-byte limit) but we enforce here defensively.
PASSWORD_MAX = 128
EMAIL_MAX    = 254    # RFC 5321 maximum
USERNAME_MAX = 20     # matches USERNAME_PATTERN in auth_policy.py
TOKEN_MAX    = 2048   # JWTs are typically <1 KB; 2 KB is generous
UUID_MAX     = 36     # "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# ── Annotated types used directly in Pydantic models ─────────────────────────

PasswordField = Annotated[
    str,
    Field(min_length=1, max_length=PASSWORD_MAX, description="User password"),
]

EmailField = Annotated[
    str,
    Field(max_length=EMAIL_MAX, description="User email address"),
]

UsernameField = Annotated[
    str,
    Field(min_length=3, max_length=USERNAME_MAX, description="Display username"),
]

RefreshTokenField = Annotated[
    str,
    Field(min_length=10, max_length=TOKEN_MAX, description="Supabase refresh token"),
]

# ── UUID path-parameter validator ─────────────────────────────────────────────

def validated_uuid(param_name: str = "id"):
    """
    Returns a FastAPI Path() that enforces UUID v4 format on a path parameter.
    FastAPI raises HTTP 422 for any non-UUID value before route handler code runs.

    NOTE: Path(alias=) does NOT remap path parameters — path params are always
    matched by the function argument name, not an alias. The param_name arg is
    used only for the description string.

    Usage:
        prediction_id: str = validated_uuid("prediction_id")
    """
    return Path(
        ...,
        min_length=36,
        max_length=UUID_MAX,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description=f"UUID v4 identifier ({param_name})",
    )


def parse_uuid(value: str, field_name: str = "id") -> str:
    """
    Strict UUID parse — raises HTTP 422 if the value is not a valid UUID.
    Use this inside service functions for belt-and-suspenders validation
    on top of the Path() pattern above.
    """
    try:
        return str(_uuid.UUID(value, version=4))
    except ValueError:
        raise HTTPException(422, f"Invalid {field_name}: must be a UUID v4.")


# ── BBox coordinate limits ────────────────────────────────────────────────────

# Max image dimension accepted by security.py — used to clamp bbox floats.
# Floats outside [0, MAX_IMAGE_DIM] cannot be legitimate pixel coordinates.
MAX_IMAGE_DIM = 4096.0

BBoxCoord = Annotated[
    float,
    Field(ge=0.0, le=MAX_IMAGE_DIM, description="Pixel coordinate within image bounds"),
]
