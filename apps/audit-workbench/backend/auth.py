"""On-behalf-of identity from Databricks Apps forwarded headers.

With user_api_scopes declared on the app, the Apps proxy forwards:
  X-Forwarded-Access-Token, X-Forwarded-Email, X-Forwarded-Preferred-Username, X-Forwarded-User
The token is the bearer for warehouse, FMAPI, Genie, and Lakebase credential minting,
so UC permissions apply to the real user.

Local dev: APP_DEV_ALLOW_ANONYMOUS=1 boots without the proxy (UC routes still need a token).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from .config import get_settings


@dataclass(frozen=True)
class CallerIdentity:
    email: str
    user_id: str | None
    access_token: str | None  # None only in local anonymous mode

    @property
    def is_anonymous(self) -> bool:
        return self.access_token is None

    @property
    def display_name(self) -> str:
        return self.email.split("@")[0].replace(".", " ").title()

    @property
    def initials(self) -> str:
        parts = self.display_name.split()
        return (f"{parts[0][0]}{parts[-1][0]}" if len(parts) >= 2 else self.display_name[:2]).upper()


def caller_identity(request: Request) -> CallerIdentity:
    h = request.headers
    token = h.get("x-forwarded-access-token")
    email = h.get("x-forwarded-email") or h.get("x-forwarded-preferred-username")
    if token and email:
        return CallerIdentity(email=email, user_id=h.get("x-forwarded-user"), access_token=token)
    s = get_settings()
    if s.dev_allow_anonymous:
        return CallerIdentity(email=s.dev_user_email, user_id=None, access_token=None)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                        "Missing user identity (X-Forwarded-Access-Token + X-Forwarded-Email).")
