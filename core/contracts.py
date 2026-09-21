from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator
from policy_import.models import Model


def aware(value: str | None):
    if value is not None and datetime.fromisoformat(value).tzinfo is None:
        raise ValueError("日時はタイムゾーンオフセットを含む ISO 8601 形式で入力してください。")
    return value


class TripRequest(Model):
    schema_version: Literal["1.0"] = "1.0"
    trip_id: str = Field(min_length=1)
    company_id: str | None
    employee_id: str | None
    origin: str | None
    destination: str | None
    departure_at: str | None
    return_by: str | None
    arrive_by: str | None
    purpose: str | None
    travelers: int | None = Field(default=None, ge=1)
    lodging_required: bool | None
    confirmed: bool = False
    _times = field_validator("departure_at", "return_by", "arrive_by")(aware)

    @model_validator(mode="after")
    def chronological(self):
        if self.departure_at and self.return_by and datetime.fromisoformat(self.return_by) <= datetime.fromisoformat(self.departure_at):
            raise ValueError("帰着日時は出発日時より後にしてください。")
        if self.arrive_by and self.departure_at and datetime.fromisoformat(self.arrive_by) < datetime.fromisoformat(self.departure_at):
            raise ValueError("到着期限は出発日時より前にできません。")
        if self.arrive_by and self.return_by and datetime.fromisoformat(self.arrive_by) > datetime.fromisoformat(self.return_by):
            raise ValueError("到着期限は帰着期限より後にできません。")
        return self


class CostItem(Model):
    description: str = Field(min_length=1)
    category: Literal["transport", "hotel", "transfer", "per_diem"]
    currency: Literal["JPY"]
    unit_amount: int | None = Field(ge=0)
    quantity: int = Field(ge=1)
    unit: str = Field(min_length=1)
    taxes_included: bool | None
    source: str = Field(min_length=1)
    queried_at: str
    _time = field_validator("queried_at")(aware)


class Leg(Model):
    direction: Literal["outbound", "return"]
    mode: str = Field(min_length=1)
    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    departure_at: str
    arrival_at: str
    source: str = Field(min_length=1)
    _times = field_validator("departure_at", "arrival_at")(aware)

    @model_validator(mode="after")
    def forward(self):
        if datetime.fromisoformat(self.arrival_at) <= datetime.fromisoformat(self.departure_at):
            raise ValueError("移動区間の到着日時は出発日時より後にしてください。")
        return self


class PlanInput(Model):
    schema_version: Literal["1.0"] = "1.0"
    plan_id: str = Field(min_length=1)
    trip_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    data_kind: Literal["real", "simulation"]
    available: bool | None
    valid_until: str | None
    source: str = Field(min_length=1)
    queried_at: str
    legs: list[Leg]
    costs: list[CostItem]
    # A cost category with zero cost must have an explicit reason, not silent omission.
    zero_cost_reasons: dict[Literal["transport", "hotel", "transfer", "per_diem"], str]
    _times = field_validator("valid_until", "queried_at")(aware)


class ToolResult(Model):
    status: Literal["success", "not_configured", "invalid_input", "failed", "no_results"]
    source: str | None
    queried_at: str
    data: list[dict]
    issues: list[str]


class NaturalLanguageInput(Model):
    text: str = Field(min_length=1, max_length=4000)
    base_time: str

    _time = field_validator("base_time")(aware)

    @model_validator(mode="after")
    def valid_reference_time(self):
        if datetime.fromisoformat(self.base_time).tzinfo is None:
            raise ValueError("基準時刻にはタイムゾーンオフセットを指定してください。")
        return self
