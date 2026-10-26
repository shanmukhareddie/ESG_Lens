from typing import Literal
from pydantic import BaseModel, Field, field_validator, ValidationError

class EmissionRecord(BaseModel):
    ticker: str
    metric : Literal["ghg_scope1", "ghg_scope2_location", "ghg_scope2_market", "ghg_scope3", "ghg_total_location", "ghg_total_market"]
    year : int = Literal[2024, 2025]
    value : float = Field(ge=0)
    unit_as_printed : str
    page : int= Field(ge=1)
    quote : str = Field(min_length=1)

    @field_validator("unit_as_printed")
    @classmethod
    def is_unit_as_printed_valid(cls, v:str) -> str:
        if len(v) == 0:
            raise ValueError Not_good
        return v

    

