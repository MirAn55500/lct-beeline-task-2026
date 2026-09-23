from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    module: str
    status: str


class EngineerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    transport: str
    transport_label: str
    skill: str | None = None
