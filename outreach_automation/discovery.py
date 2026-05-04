from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .compliance import can_fetch_url, domain_from_url, extract_emails
from .config import Settings
from .models import Lead

LOGGER = logging.getLogger(__name__)
USER_AGENT = "DenverOdorProsOutreachBot/1.0 (+mailto:denverodorpros@gmail.com)"

CONTACT_LINK_MARKERS = ("contact", "agent", "broker", "team", "about", "office", "email")

ADDRESSISH_RE = re.compile(
    r"\b\d{2,6}\s+[a-z0-9 .'-]+(?:st|street|ave|avenue|rd|road|dr|drive|ln|lane|way|ct|court|pl|place|blvd|circle|cir|trail|trl|pkwy|parkway)\b",
    re.IGNORECASE,
)


# 🔥 FIXED: accept agent pages + listings
def _looks_like_listing_candidate(candidate: dict) -> bool:
    link = candidate.get("link", "").lower()
    title = candidate.get("title", "")
    snippet = candidate.get("snippet", "")
    text = f"{link} {title} {snippet}".lower()

    # Accept agent pages
    if any(marker in link for marker in ["/agent/", "/agents/", "/real-estate-agent/"]):
        return True

    # Accept if looks like address
    if ADDRESSISH_RE.search(f"{title} {snippet}"):
        return True

    # Accept general real estate content
    if any(word in text for word in ["agent", "realtor", "broker", "real estate"]):
        return True

    return False


def _fetch_soup(url: str) -> BeautifulSoup | None:
    try:
        response = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
        if response.status_code >= 400:
            LOGGER.info("Skipping %s: HTTP %s", url, response.status_code)
            return None
    except requests.RequestException as exc:
        LOGGER.info("Skipping %s: %s", url, exc)
        return None

    return BeautifulSoup(response.text, "html.parser")


def _extract_page_emails(soup: BeautifulSoup, page_text: str) -> list[str]:
    emails = extract_emails(page_text)

    # also check mailto links
    for link in soup.select("a[href^='mailto:']"):
        href = link.get("href", "")
        email = href.replace("mailto:", "").split("?")[0].strip()
        if email:
            emails.append(email)

    # unique only
    seen = set()
    unique = []
    for e in emails:
        if e not in seen:
            seen.add(e)
            unique.append(e)

    return unique


def fetch_lead_from_candidate(candidate: dict, settings: Settings) -> Lead | None:
    url = candidate.get("link", "")
    if not url:
        return None

    if not _looks_like_listing_candidate(candidate):
        LOGGER.info("Skipping %s: not relevant", url)
        return None

    decision = can_fetch_url(url, settings.allowed_fetch_domains, settings.blocked_domains, USER_AGENT)
    if not decision.allowed:
        LOGGER.info("Skipping %s: %s", url, decision.reason)
        return None

    soup = _fetch_soup(url)
    if not soup:
        return None

    text = soup.get_text(" ", strip=True)
    emails = _extract_page_emails(soup, text)

    if not emails:
        LOGGER.info("No email found on page, skipping: %s", url)
        return None

    domain = domain_from_url(url)

    return Lead(
        property_address=candidate.get("title", "") or candidate.get("snippet", ""),
        listing_url=url,
        agent_name="Listing Agent",
        brokerage_name=domain,
        email=emails[0],
        source=f"{settings.search_provider}:{urlparse(url).netloc}",
    )


def search_candidates(settings: Settings, limit: int = 10) -> list[dict]:
    if settings.search_provider == "brave":
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={
                "q": settings.search_query,
                "count": min(limit, 20),
            },
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": settings.brave_search_api_key,
            },
            timeout=20,
        )

        data = response.json()
        results = data.get("web", {}).get("results", [])

        return [
            {
                "link": r.get("url"),
                "title": r.get("title"),
                "snippet": r.get("description"),
            }
            for r in results
        ]

    raise RuntimeError("Only Brave search supported in this version")


def discover_leads(settings: Settings, limit: int = 2) -> list[Lead]:
    leads = []
    seen_emails = set()

    for candidate in search_candidates(settings, limit=20):
        lead = fetch_lead_from_candidate(candidate, settings)
        if not lead:
            continue

        email = lead.email.lower()
        if email in seen_emails:
            continue

        seen_emails.add(email)
        leads.append(lead)

        if len(leads) >= limit:
            break

    return leads


def discover_one_lead(settings: Settings) -> Lead | None:
    leads = discover_leads(settings, limit=1)
    return leads[0] if leads else None