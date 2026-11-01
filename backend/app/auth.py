import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User


ALGORITHM = "HS256"
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    password_digest = hashlib.sha256(password.encode()).digest()
    return bcrypt.hashpw(password_digest, bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    password_digest = hashlib.sha256(password.encode()).digest()
    return bcrypt.checkpw(password_digest, password_hash.encode())


def create_access_token(user: User) -> str:
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    return jwt.encode(
        {"sub": str(user.id), "role": user.role, "exp": expires},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in is required.")
    try:
        user_id = UUID(jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[ALGORITHM])["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired access token.")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account no longer exists.")
    return user


def require_authority(user: User = Depends(get_current_user)) -> User:
    if user.role not in {"authority", "admin"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Authority access is required.")
    return user
