from typing import Literal

from pydantic import BaseModel, Field, field_validator

Metric = Literal["ghg_scope1", "ghg_scope2_location", "ghg_scope2_market",
                 "ghg_scope3", "ghg_total_location", "ghg_total_market"]


class EmissionRecord(BaseModel):
    """One emissions figure read from a report, with the page and text it came from."""

    ticker: str
    metric: Metric
    year: Literal[2024, 2025]
    value: float = Field(ge=0)          # as printed, e.g. 480 when the table is in ktCO2e
    unit_as_printed: str
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)

    @field_validator("unit_as_printed")
    @classmethod
    def unit_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("unit_as_printed is empty")
        return v.strip()
