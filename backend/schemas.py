from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


Severity = Literal["critical", "high", "medium", "low"]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class ReportInput(BaseModel):
    packageName: str = Field(min_length=1)
    affectedVersion: str = Field(min_length=1)
    submitterEmail: EmailStr
    description: str = Field(min_length=26)
    severity: Severity
    agreedToTerms: bool

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

    @field_validator("agreedToTerms")
    @classmethod
    def require_terms(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Terms must be accepted.")

        return value
class RegisterRequest(LoginRequest):
    name: str = Field(min_length=1)