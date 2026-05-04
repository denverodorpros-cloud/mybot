from __future__ import annotations

import re
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlparse

import requests


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PERSONAL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "aol.com",
    "msn.com",
    "live.com",
    "proton.me",
    "protonmail.com",
}


@dataclass(frozen=True)
class FetchDecision:
    allowed: bool
    reason: str


def domain_from_url(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def email_domain(email: str) -> str:
    return email.split("@", 1)[-1].strip().lower()


def looks_like_business_email(email: str, surrounding_text: str = "") -> bool:
    domain = email_domain(email)
    if domain not in PERSONAL_DOMAINS:
        return True
    business_markers = ("real estate", "realtor", "broker", "listing agent", "contact", "office", "business")
    return any(marker in surrounding_text.lower() for marker in business_markers)


def extract_emails(text: str) -> list[str]:
    seen: set[str] = set()
    emails: list[str] = []
    for match in EMAIL_RE.finditer(text):
        email = match.group(0).strip().lower()
        if email not in seen and looks_like_business_email(email, text[max(0, match.start() - 200) : match.end() + 200]):
            seen.add(email)
            emails.append(email)
    return emails


def can_fetch_url(url: str, allowed_domains: set[str], blocked_domains: set[str], user_agent: str) -> FetchDecision:
    domain = domain_from_url(url)
    if domain in blocked_domains or any(domain.endswith(f".{blocked}") for blocked in blocked_domains):
        return FetchDecision(False, f"{domain} is blocked by configuration")
    if domain not in allowed_domains and not any(domain.endswith(f".{allowed}") for allowed in allowed_domains):
        return FetchDecision(False, f"{domain} is not in ALLOWED_FETCH_DOMAINS")

    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    try:
        response = requests.get(robots_url, timeout=10, headers={"User-Agent": user_agent})
        if response.status_code >= 400:
            return FetchDecision(False, f"robots.txt unavailable with status {response.status_code}")
        parser.parse(response.text.splitlines())
    except requests.RequestException as exc:
        return FetchDecision(False, f"robots.txt check failed: {exc}")

    if not parser.can_fetch(user_agent, url):
        return FetchDecision(False, "robots.txt disallows this URL")
    return FetchDecision(True, "allowed")
