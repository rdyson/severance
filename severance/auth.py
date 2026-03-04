"""Basic auth middleware for FastAPI."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from severance.config import AuthConfig

security = HTTPBasic()

_auth_config: AuthConfig | None = None


def set_auth_config(config: AuthConfig) -> None:
    global _auth_config
    _auth_config = config


def verify_credentials(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
) -> str:
    """Verify basic auth credentials. Returns username."""
    if _auth_config is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth not configured",
        )

    username_ok = secrets.compare_digest(
        credentials.username.encode(), _auth_config.username.encode()
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode(), _auth_config.password.encode()
    )

    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username
