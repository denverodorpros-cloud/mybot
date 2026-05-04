from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _csv(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    dry_run: bool
    daily_send_limit: int
    database_path: Path
    log_level: str
    schedule_time: str
    timezone: str
    gmail_sender: str
    gmail_client_secret_file: Path
    gmail_token_file: Path
    business_name: str
    contact_name: str
    business_email: str
    business_website: str
    business_phone: str
    business_address: str
    logo_path: Path
    google_search_api_key: str
    google_search_engine_id: str
    search_provider: str
    brave_search_api_key: str
    allowed_fetch_domains: set[str]
    blocked_domains: set[str]
    search_query: str

    @property
    def ready_to_send(self) -> bool:
        placeholders = {"", "[phone number]", "[physical mailing address]", "[business mailing address]"}
        return (
            self.business_phone.strip() not in placeholders
            and self.business_address.strip() not in placeholders
            and self.gmail_sender.strip().lower() == "denverodorpros@gmail.com"
        )


def load_settings(env_file: str | Path = ".env") -> Settings:
    load_dotenv(env_file)
    return Settings(
        dry_run=_bool(os.getenv("DRY_RUN"), default=True),
        daily_send_limit=int(os.getenv("DAILY_SEND_LIMIT", "2")),
        database_path=Path(os.getenv("DATABASE_PATH", "data/outreach.sqlite3")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        schedule_time=os.getenv("SCHEDULE_TIME", "12:20"),
        timezone=os.getenv("TIMEZONE", "America/Denver"),
        gmail_sender=os.getenv("GMAIL_SENDER", "denverodorpros@gmail.com"),
        gmail_client_secret_file=Path(os.getenv("GMAIL_CLIENT_SECRET_FILE", "secrets/gmail_client_secret.json")),
        gmail_token_file=Path(os.getenv("GMAIL_TOKEN_FILE", "secrets/gmail_token.json")),
        business_name=os.getenv("BUSINESS_NAME", "Denver Odor Pros"),
        contact_name=os.getenv("CONTACT_NAME", "Max"),
        business_email=os.getenv("BUSINESS_EMAIL", "denverodorpros@gmail.com"),
        business_website=os.getenv("BUSINESS_WEBSITE", "www.denverodorpros.com"),
        business_phone=os.getenv("BUSINESS_PHONE", "[phone number]"),
        business_address=os.getenv("BUSINESS_ADDRESS", "[physical mailing address]"),
        logo_path=Path(os.getenv("LOGO_PATH", "assets/denver-odor-pros-logo.png")),
        google_search_api_key=os.getenv("GOOGLE_SEARCH_API_KEY", ""),
        google_search_engine_id=os.getenv("GOOGLE_SEARCH_ENGINE_ID", ""),
        search_provider=os.getenv("SEARCH_PROVIDER", "brave").strip().lower(),
        brave_search_api_key=os.getenv("BRAVE_SEARCH_API_KEY", ""),
        allowed_fetch_domains=_csv(os.getenv("ALLOWED_FETCH_DOMAINS")),
        blocked_domains=_csv(os.getenv("BLOCKED_DOMAINS")) or {"zillow.com", "trulia.com", "realtor.com", "redfin.com"},
        search_query=os.getenv(
            "SEARCH_QUERY",
            '("active listing" OR "for sale") ("listing agent" OR "brokerage") email Denver Colorado',
        ),
    )
