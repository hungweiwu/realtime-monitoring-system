from fastapi import APIRouter

from app.core.deps import CurrentUser
from app.models import User
from app.schemas.user import UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def read_me(user: CurrentUser) -> User:
    return user
