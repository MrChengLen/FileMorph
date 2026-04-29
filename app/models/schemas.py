from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str
    ffmpeg_available: bool


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]


class FormatsResponse(BaseModel):
    conversions: dict[str, list[str]]
    compression: dict[str, list[str]]


class ErrorResponse(BaseModel):
    detail: str
