from pydantic import BaseModel, EmailStr, Field

from app.models.auth import UserRole
from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class UserOut(ORMModel):
    id: int
    email: str
    role: UserRole
    is_active: bool


class CsrfOut(BaseModel):
    csrf_token: str
