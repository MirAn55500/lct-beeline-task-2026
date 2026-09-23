from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    module: str
    status: str


class RegionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(validation_alias="region_id")
    name: str = Field(validation_alias="region_name")
