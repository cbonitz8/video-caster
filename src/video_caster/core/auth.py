"""Local-client token: proves a request comes from this Mac, not the tailnet.

The source address can't tell them apart, because tailscale serve forwards phone
requests from 127.0.0.1.
"""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path

from video_caster.core.errors import Forbidden, Unauthorized


def new_token() -> str:
    return secrets.token_urlsafe(32)


def save_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    os.chmod(path, 0o600)  # O_CREAT's mode doesn't apply to an existing file


def write_token(path: Path) -> str:
    token = new_token()
    save_token(path, token)
    return token


def is_local(authorization: str | None, token: str) -> bool:
    if authorization is None:
        return False
    if hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
        return True
    raise Forbidden("Invalid token")


def require_local(authorization: str | None, token: str) -> None:
    if authorization is None:
        raise Unauthorized("This action is only available on the Mac")
    is_local(authorization, token)
