from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


Severity = Literal["critical", "high", "medium", "low"]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class ReportInput(BaseModel):
    reportCode: str | None = Field(default=None, min_length=3, max_length=80)
    packageName: str = Field(min_length=1)
    affectedVersion: str = Field(min_length=1)
    submitterEmail: EmailStr
    description: str = Field(min_length=26)
    severity: Severity
    agreedToTerms: bool
    advisoryId: int | None = Field(default=None, ge=1)
    availableCount: int = Field(default=1, ge=0)

    @field_validator(
        "packageName",
        "affectedVersion",
        "description",
    )
    @classmethod
    def remove_extra_spaces(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("This field cannot be blank.")

        return value

    @field_validator("reportCode")
    @classmethod
    def validate_report_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Report code cannot be blank.")
        return value

    @field_validator("agreedToTerms")
    @classmethod
    def require_terms(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Terms must be accepted.")

        return value
class RegisterRequest(LoginRequest):
    name: str = Field(min_length=1)


class AdvisoryInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    publisher: str = Field(min_length=1, max_length=255)
    advisoryCode: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")

    @field_validator("name", "publisher", "advisoryCode")
    @classmethod
    def trim_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value


class AdvisoryResponse(AdvisoryInput):
    id: int
    createdAt: datetime
    updatedAt: datetime
