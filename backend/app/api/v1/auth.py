from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.deps import SessionDep
from app.core.security import create_access_token
from app.models import User
from app.schemas.user import Token, UserRead, UserRegister
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister, session: SessionDep) -> User:
    return await user_service.register(session, payload)


@router.post("/login", response_model=Token)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep
) -> Token:
    user = await user_service.authenticate(session, form.username, form.password)
    return Token(access_token=create_access_token(user.id))
