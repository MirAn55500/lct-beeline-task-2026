from pydantic import BaseModel


class HealthResponse(BaseModel):
    module: str
    status: str
