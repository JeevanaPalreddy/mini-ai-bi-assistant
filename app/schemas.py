"""Pydantic models shared by the interpreter, analytics layer, and API."""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

Metric = Literal["revenue", "orders", "units", "avg_order_value", "total_discount"]
Dimension = Literal["product", "category", "region", "sales_channel", "order_month"]
FilterDimension = Literal["product", "category", "region", "sales_channel"]

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


class QuerySpec(BaseModel):
    """A structured, validated description of what the user asked for."""

    metric: Metric = "revenue"
    group_by: Optional[Dimension] = None
    filters: Dict[FilterDimension, str] = Field(default_factory=dict)
    start_month: Optional[str] = Field(default=None, pattern=MONTH_PATTERN)
    end_month: Optional[str] = Field(default=None, pattern=MONTH_PATTERN)
    limit: Optional[int] = Field(default=None, ge=1, le=100)
    sort: Literal["desc", "asc"] = "desc"

    @model_validator(mode="after")
    def order_months(self):
        if self.start_month and self.end_month and self.start_month > self.end_month:
            self.start_month, self.end_month = self.end_month, self.start_month
        return self


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=500)


class ResultRow(BaseModel):
    label: str
    value: float


class AskResponse(BaseModel):
    question: str
    interpreted_by: Literal["llm", "rule_based_fallback"]
    notice: Optional[str] = None
    spec: QuerySpec
    description: str
    rows: List[ResultRow]
    total: Optional[float] = None