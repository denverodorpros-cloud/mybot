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
LISTING_MARKERS = (
    "home-details",
    "property",
    "listing",
    "for-sale",
    "homes-for-sale",
    "mls",
    "bed",
    "bath",
    "sqft",
    "address",
)
ADDRESSISH_RE = re.compile(r"\b\d{2,6}\s+[a-z0-9 .'-]+(?:st|street|ave|avenue|rd|road|dr|drive|ln|lane|way|ct|court|pl|place|blvd|circle|cir|trail|trl|pkwy|parkway)\b", re.IGNORECASE)


def _google_search_candidates(settings: Settings, limit: int) -> list[dict]:
    if not settings.google_search_api_key or not settings.google_search_engine_id:
        LOGGER.warning("Google search credentials are not configured")
        return []

    response = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={
            "key": settings.google_search_api_key,
            "cx": settings.google_search_engine_id,
            "q": settings.search_query,
            "num": min(limit, 10),
            "safe": "active",
        },
        timeout=20,
    )
    if response.status_code >= 400:
        try:
            error = response.json().get("error", {})
            message = error.get("message", response.text[:300])
            reason = ", ".join(item.get("reason", "") for item in error.get("errors", []) if item.get("reason"))
        except ValueError:
            message = response.text[:300]
            reason = ""
        detail = f"{response.status_code} {message}"
        if reason:
            detail = f"{detail} ({reason})"
        raise RuntimeError(f"Google Custom Search request failed: {detail}")
    payload = response.json()
    return payload.get("items", [])


def _site_filters(settings: Settings, group_size: int = 4) -> list[str]:
    domains = sorted(settings.allowed_fetch_domains)
    if not domains:
        return [""]
    filters: list[str] = []
    for index in range(0, len(domains), group_size):
        group = domains[index : index + group_size]
        filters.append("(" + " OR ".join(f"site:{domain}" for domain in group) + ")")
    return filters


def _shorten_query(query: str, max_length: int = 390) -> str:
    words = query.split()
    if len(words) > 48:
        query = " ".join(words[:48])
    if len(query) <= max_length:
        return query
    return query[:max_length].rsplit(" ", 1)[0]


def _brave_queries(settings: Settings) -> list[str]:
    site_filters = _site_filters(settings)
    locations = '("Denver CO" OR "Castle Rock CO" OR "Parker CO" OR "Aurora CO" OR "Colorado Springs CO") -"Denver NC"'
    query_parts = [
        settings.search_query,
        f'("for sale" OR listing) ("listing agent" OR realtor) (email OR mailto OR "@") {locations}',
        f'(MLS OR "home for sale") ("listing agent" OR "brokered by") (email OR "@gmail.com") {locations}',
        'agent realtor email contact Denver listing',
        '"property details" email Colorado "for sale"',
    ]
    queries: list[str] = []
    for part in query_parts:
        for site_filter in site_filters:
            query = _shorten_query(f"({part}) {site_filter}".strip())
            if query not in queries:
                queries.append(query)
    return queries


def _brave_search_one(settings: Settings, query: str, limit: int) -> list[dict]:
    response = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={
            "q": query,
            "count": min(limit, 20),
            "search_lang": "en",
            "country": "US",
            "safesearch": "moderate",
            "spellcheck": "1",
        },
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": settings.brave_search_api_key,
        },
        timeout=20,
    )
    if response.status_code >= 400:
        try:
            message = response.json()
        except ValueError:
            message = response.text[:300]
        raise RuntimeError(f"Brave Search request failed: {response.status_code} {message}")

    payload = response.json()
    results = payload.get("web", {}).get("results", [])
    return [
        {
            "link": result.get("url", ""),
            "title": result.get("title", ""),
            "snippet": result.get("description", ""),
        }
        for result in results
    ]


def _brave_search_candidates(settings: Settings, limit: int) -> list[dict]:
    if not settings.brave_search_api_key or settings.brave_search_api_key == "PASTE_BRAVE_SEARCH_API_KEY_HERE":
        LOGGER.warning("Brave search credentials are not configured")
        return []

    candidates: list[dict] = []
    seen: set[str] = set()
    for query in _brave_queries(settings):
        for candidate in _brave_search_one(settings, query, limit=20):
            url = candidate.get("link", "")
            if not url or url in seen:
                continue
            seen.add(url)
            candidates.append(candidate)
            if len(candidates) >= max(limit, 40):
                return candidates
    return candidates


def search_candidates(settings: Settings, limit: int = 10) -> list[dict]:
    if settings.search_provider == "brave":
        return _brave_search_candidates(settings, limit)
    if settings.search_provider == "google":
        return _google_search_candidates(settings, limit)
    raise RuntimeError(f"Unsupported SEARCH_PROVIDER: {settings.search_provider}")


def _text_or_empty(soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            text = node.get_text(" ", strip=True)
            if text:
                return text
    return ""


def _guess_address(soup: BeautifulSoup, title: str, snippet: str) -> str:
    address = _text_or_empty(
        soup,
        [
            "[itemprop='streetAddress']",
            "[data-testid*='address']",
            ".address",
            "h1",
        ],
    )
    return address or title or snippet


def _guess_agent_name(soup: BeautifulSoup, snippet: str) -> str:
    agent = _text_or_empty(
        soup,
        [
            "[itemprop='agent']",
            "[class*='agent-name']",
            "[class*='realtor']",
            "[class*='broker']",
        ],
    )
    return agent or "Listing Agent"


def _guess_brokerage(soup: BeautifulSoup, domain: str) -> str:
    brokerage = _text_or_empty(
        soup,
        [
            "[itemprop='broker']",
            "[class*='brokerage']",
            "[class*='office']",
            "[class*='company']",
        ],
    )
    return brokerage or domain


def _looks_like_listing_candidate(candidate: dict) -> bool:
    link = candidate.get("link", "").lower()
    title = candidate.get("title", "")
    snippet = candidate.get("snippet", "")
    text = f"{link} {title} {snippet}".lower()
    profile_markers = ("/agent/", "/agents/", "/real-estate-agent/", "/agents-search")
    if any(marker in link for marker in profile_markers):
        return False
    if ADDRESSISH_RE.search(f"{title} {snippet}"):
        return True
    property_url_markers = ("home-details", "/property/", "/homes/", "/listing/", "/listings/", "/real-estate/")
    if any(marker in link for marker in property_url_markers) and any(marker in text for marker in LISTING_MARKERS):
        return True
    return False


def _extract_page_emails(soup: BeautifulSoup, page_text: str) -> list[str]:
    emails = extract_emails(page_text)
    for link in soup.select("a[href^='mailto:']"):
        href = link.get("href", "")
        email = href.removeprefix("mailto:").split("?", 1)[0].strip()
        if email:
            emails.extend(extract_emails(email))
    seen: set[str] = set()
    unique: list[str] = []
    for email in emails:
        if email not in seen:
            seen.add(email)
            unique.append(email)
    return unique


def _same_allowed_domain(url: str, base_url: str, settings: Settings) -> bool:
    candidate_domain = domain_from_url(url)
    base_domain = domain_from_url(base_url)
    if candidate_domain != base_domain:
        return False
    decision = can_fetch_url(url, settings.allowed_fetch_domains, settings.blocked_domains, USER_AGENT)
    return decision.allowed


def _contact_links(soup: BeautifulSoup, base_url: str, settings: Settings, limit: int = 4) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for node in soup.select("a[href]"):
        href = node.get("href", "")
        text = f"{node.get_text(' ', strip=True)} {href}".lower()
        if not any(marker in text for marker in CONTACT_LINK_MARKERS):
            continue
        absolute = urljoin(base_url, href).split("#", 1)[0]
        if absolute in seen or not absolute.startswith(("http://", "https://")):
            continue
        if _same_allowed_domain(absolute, base_url, settings):
            seen.add(absolute)
            links.append(absolute)
        if len(links) >= limit:
            break
    return links


def _fetch_soup(url: str) -> BeautifulSoup | None:
    try:
        response = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
        if response.status_code >= 400:
            LOGGER.info("Skipping %s: fetch returned HTTP %s", url, response.status_code)
            return None
    except requests.RequestException as exc:
        LOGGER.info("Skipping %s: fetch failed: %s", url, exc)
        return None
    return BeautifulSoup(response.text, "html.parser")


def fetch_lead_from_candidate(candidate: dict, settings: Settings) -> Lead | None:
    url = candidate.get("link", "")
    if not url:
        return None
    if not _looks_like_listing_candidate(candidate):
        LOGGER.info("Skipping %s: result does not look like a property listing", url)
        return None

    snippet_text = f"{candidate.get('title', '')} {candidate.get('snippet', '')}"
    snippet_emails = extract_emails(snippet_text)
    decision = can_fetch_url(url, settings.allowed_fetch_domains, settings.blocked_domains, USER_AGENT)
    if not decision.allowed:
        if snippet_emails:
            LOGGER.info("Found public email in search snippet, but source URL is not allowlisted: %s", url)
        LOGGER.info("Skipping %s: %s", url, decision.reason)
        return None

    soup = _fetch_soup(url)
    if soup is None:
        if snippet_emails:
            domain = domain_from_url(url)
            return Lead(
                property_address=candidate.get("title", "") or candidate.get("snippet", ""),
                listing_url=url,
                agent_name="Listing Agent",
                brokerage_name=domain,
                email=snippet_emails[0],
                source=f"brave_snippet:{urlparse(url).netloc}",
            )
        return None
    page_text = soup.get_text(" ", strip=True)
    emails = _extract_page_emails(soup, page_text)
    if not emails:
        for contact_url in _contact_links(soup, url, settings):
            contact_soup = _fetch_soup(contact_url)
            if contact_soup is None:
                continue
            emails = _extract_page_emails(contact_soup, contact_soup.get_text(" ", strip=True))
            if emails:
                break
    if not emails and snippet_emails:
        emails = snippet_emails
    if not emails:
        LOGGER.info("No public business email found on %s", url)
        return None

    domain = domain_from_url(url)
    return Lead(
        property_address=_guess_address(soup, candidate.get("title", ""), candidate.get("snippet", "")),
        listing_url=url,
        agent_name=_guess_agent_name(soup, candidate.get("snippet", "")),
        brokerage_name=_guess_brokerage(soup, domain),
        email=emails[0],
        source=f"{settings.search_provider}:{urlparse(url).netloc}",
    )


def discover_leads(settings: Settings, limit: int = 1) -> list[Lead]:
    leads: list[Lead] = []
    seen_urls: set[str] = set()
    seen_emails: set[str] = set()
    for candidate in search_candidates(settings, limit=max(20, limit * 12)):
        lead = fetch_lead_from_candidate(candidate, settings)
        if not lead:
            continue
        normalized_email = lead.email.strip().lower()
        if lead.listing_url in seen_urls or normalized_email in seen_emails:
            continue
        seen_urls.add(lead.listing_url)
        seen_emails.add(normalized_email)
        leads.append(lead)
        if len(leads) >= limit:
            break
    return leads


def discover_one_lead(settings: Settings) -> Lead | None:
    leads = discover_leads(settings, limit=1)
    return leads[0] if leads else None
