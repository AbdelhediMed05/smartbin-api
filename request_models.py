from pydantic import BaseModel, ConfigDict


class StrictRequestModel(BaseModel):
    """
    Shared request model base.
    Reject unknown fields and normalize leading/trailing whitespace
    so route handlers never process silent extras.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )
