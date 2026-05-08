from datetime import datetime

from pydantic import BaseModel


class CurrentUser(BaseModel):
    user_id: str
    google_email: str | None
    scopes: list[str]
    token_expires_at: datetime | None
