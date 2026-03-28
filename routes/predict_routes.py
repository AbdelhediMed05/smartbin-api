"""
routes/predict_routes.py — Waste image classification endpoint.

Rate limiting (OWASP A04 — Insecure Design):
  POST /predict          10/minute per USER+IP — ML inference is expensive;
    user+IP combined key prevents a single account from bypassing the limit
    via rotating proxies AND prevents a shared NAT IP from locking out all users.
  DELETE /predict/{id}/cancel  30/minute per USER+IP — cancel is lightweight
    but still bounded to prevent storage-cleanup DoS.

Input validation (OWASP A03):
  - prediction_id path parameter validated as UUID v4 via regex in Path().
  - conf form field validated with ge/le bounds (already present, kept).
  - File is validated in predict_service via magic-byte MIME check + PIL verify.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, Response, UploadFile

from auth import get_current_user
from limiter import get_user_or_ip, limiter
from services.predict_service import cancel_prediction as cancel_prediction_service
from services.predict_service import predict_image
from validators import validated_uuid

router = APIRouter(tags=["predict"])


@router.post("/predict")
@limiter.limit("10/minute", key_func=get_user_or_ip)   # user+IP bucket
async def predict(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    # ge/le enforce 0.1–0.9 before service layer; FastAPI returns 422 on violation
    conf: float = Form(default=0.45, ge=0.1, le=0.9),
    current_user: dict = Depends(get_current_user),
):
    # Expose user_id on request.state so get_user_or_ip() can read it
    request.state.user_id = current_user["user_id"]
    client_ip = request.client.host if request.client else "unknown"
    return predict_image(
        user_id=current_user["user_id"],
        upload_file=file,
        conf=conf,
        client_ip=client_ip,
    )


@router.delete("/predict/{prediction_id}/cancel")
@limiter.limit("30/minute", key_func=get_user_or_ip)
async def cancel_prediction(
    request: Request,
    response: Response,
    prediction_id: str = validated_uuid("prediction_id"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: dict = Depends(get_current_user),
):
    request.state.user_id = current_user["user_id"]
    return cancel_prediction_service(
        prediction_id=prediction_id,
        user_id=current_user["user_id"],
        background_tasks=background_tasks,
    )
