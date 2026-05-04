from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Lead:
    property_address: str
    listing_url: str
    agent_name: str
    brokerage_name: str
    email: str
    source: str


@dataclass(frozen=True)
class EmailMessage:
    subject: str
    body: str
    html_body: str | None = None
