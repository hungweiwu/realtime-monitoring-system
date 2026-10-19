from pydantic import BaseModel, ConfigDict, Field

from app.models import Role
from app.schemas.common import UTCDatetimeOut


class UserRegister(BaseModel):
    # extra="forbid"：多帶欄位（例如 role）直接 422，杜絕註冊時自行指定角色
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: Role
    is_active: bool
    created_at: UTCDatetimeOut


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
