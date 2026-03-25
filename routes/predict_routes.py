from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from slowapi import Limiter
from slowapi.util import get_remote_address

from auth import get_current_user
from services.predict_service import cancel_prediction as cancel_prediction_service
from services.predict_service import predict_image

router = APIRouter(tags=["predict"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/predict")
@limiter.limit("10/minute")
async def predict(
    request: Request,
    file: UploadFile = File(...),
    conf: float = Form(default=0.45, ge=0.1, le=0.9),
    current_user: dict = Depends(get_current_user),
):
    client_ip = request.client.host if request.client else "unknown"
    return predict_image(
        user_id=current_user["user_id"],
        upload_file=file,
        conf=conf,
        client_ip=client_ip,
    )


@router.delete("/predict/{prediction_id}/cancel")
async def cancel_prediction(
    request: Request,
    prediction_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    return cancel_prediction_service(
        prediction_id=prediction_id,
        user_id=current_user["user_id"],
        background_tasks=background_tasks,
    )
