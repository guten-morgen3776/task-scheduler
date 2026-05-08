import asyncio
import logging
from datetime import UTC, datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_or_create_default_user
from app.core.config import get_settings
from app.core.crypto import get_cipher
from app.models import OAuthCredential, User

logger = logging.getLogger("app.google")


class GoogleAuthError(Exception):
    pass


class NotAuthenticatedError(GoogleAuthError):
    pass


class ReauthRequiredError(GoogleAuthError):
    pass


def _credentials_to_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
        "expiry": creds.expiry,
    }


async def start_local_flow(db: AsyncSession) -> User:
    """Run the InstalledAppFlow in the local browser and persist tokens.

    Returns the User the credentials were saved against.
    Blocks while the user authorizes — do not call from a running event loop synchronously.
    """
    settings = get_settings()

    def _run_flow() -> Credentials:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(settings.google_credentials_path),
            scopes=settings.google_oauth_scopes,
        )
        return flow.run_local_server(port=0, prompt="consent")

    creds: Credentials = await asyncio.get_running_loop().run_in_executor(None, _run_flow)

    if not creds.refresh_token:
        raise GoogleAuthError(
            "No refresh_token returned. Re-run authorization with prompt=consent."
        )

    google_email = await _fetch_google_email(creds)

    user = await get_or_create_default_user(db)
    if google_email and not user.google_email:
        user.google_email = google_email
    await db.flush()

    await _save_credentials(db, user.id, creds)
    return user


async def _fetch_google_email(creds: Credentials) -> str | None:
    def _call() -> str | None:
        try:
            service = build("oauth2", "v2", credentials=creds, cache_discovery=False)
            info = service.userinfo().get().execute()
            return info.get("email")
        except HttpError as e:
            logger.warning("Failed to fetch Google userinfo: %s", e)
            return None

    return await asyncio.get_running_loop().run_in_executor(None, _call)


async def _save_credentials(db: AsyncSession, user_id: str, creds: Credentials) -> None:
    cipher = get_cipher()
    settings = get_settings()
    refresh_encrypted = cipher.encrypt(creds.refresh_token)
    access_encrypted = cipher.encrypt(creds.token) if creds.token else None
    expires_at = creds.expiry.replace(tzinfo=UTC) if creds.expiry else None
    scopes = " ".join(creds.scopes or settings.google_oauth_scopes)

    existing = (
        await db.execute(select(OAuthCredential).where(OAuthCredential.user_id == user_id))
    ).scalar_one_or_none()

    if existing is None:
        db.add(
            OAuthCredential(
                user_id=user_id,
                provider="google",
                refresh_token_encrypted=refresh_encrypted,
                access_token_encrypted=access_encrypted,
                token_expires_at=expires_at,
                scopes=scopes,
            )
        )
    else:
        existing.refresh_token_encrypted = refresh_encrypted
        existing.access_token_encrypted = access_encrypted
        existing.token_expires_at = expires_at
        existing.scopes = scopes


async def load_credentials(db: AsyncSession, user_id: str) -> Credentials:
    record = (
        await db.execute(select(OAuthCredential).where(OAuthCredential.user_id == user_id))
    ).scalar_one_or_none()
    if record is None:
        raise NotAuthenticatedError(f"No OAuth credentials for user {user_id}")

    cipher = get_cipher()
    settings = get_settings()

    with open(settings.google_credentials_path) as f:
        import json

        client_config = json.load(f)
    installed = client_config.get("installed") or client_config.get("web") or {}

    refresh_token = cipher.decrypt(record.refresh_token_encrypted)
    access_token = (
        cipher.decrypt(record.access_token_encrypted) if record.access_token_encrypted else None
    )

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=installed.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=installed["client_id"],
        client_secret=installed["client_secret"],
        scopes=record.scopes.split(" ") if record.scopes else settings.google_oauth_scopes,
    )
    if record.token_expires_at is not None:
        creds.expiry = record.token_expires_at.replace(tzinfo=None)

    if not creds.valid:
        try:
            await asyncio.get_running_loop().run_in_executor(None, creds.refresh, Request())
        except Exception as e:
            raise ReauthRequiredError(f"Failed to refresh token: {e}") from e

        record.access_token_encrypted = cipher.encrypt(creds.token) if creds.token else None
        record.token_expires_at = creds.expiry.replace(tzinfo=UTC) if creds.expiry else None
        await db.flush()

    return creds


async def delete_credentials(db: AsyncSession, user_id: str) -> bool:
    record = (
        await db.execute(select(OAuthCredential).where(OAuthCredential.user_id == user_id))
    ).scalar_one_or_none()
    if record is None:
        return False
    await db.delete(record)
    return True


async def get_credential_info(
    db: AsyncSession, user_id: str
) -> tuple[list[str], datetime | None] | None:
    record = (
        await db.execute(select(OAuthCredential).where(OAuthCredential.user_id == user_id))
    ).scalar_one_or_none()
    if record is None:
        return None
    scopes = record.scopes.split(" ") if record.scopes else []
    return scopes, record.token_expires_at
