from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import Settings
from .db import Database
from .discovery import discover_leads, discover_one_lead
from .email_template import render_email
from .gmail_client import send_email
from .models import Lead

LOGGER = logging.getLogger(__name__)


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    for marker in ("key=", "access_token=", "token="):
        if marker in text:
            parts = []
            for word in text.split():
                if marker in word:
                    try:
                        split = urlsplit(word)
                        if split.query:
                            query = []
                            for key, value in parse_qsl(split.query, keep_blank_values=True):
                                query.append((key, "[redacted]" if key.lower() in {"key", "access_token", "token"} else value))
                            word = urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))
                    except ValueError:
                        word = "[redacted-url]"
                parts.append(word)
            text = " ".join(parts)
    return text


def _row_to_lead(row) -> Lead:
    return Lead(
        property_address=row["property_address"],
        listing_url=row["listing_url"],
        agent_name=row["agent_name"],
        brokerage_name=row["brokerage_name"],
        email=row["email"],
        source=row["source"],
    )


def process_lead(settings: Settings, db: Database, *, lead_id: int, lead: Lead, dry_run: bool) -> str:
    if db.is_suppressed(lead.email, lead.brokerage_name):
        db.mark_lead_status(lead_id, "suppressed")
        db.log("skipped", "Lead is suppressed", lead.email)
        return f"Skipped suppressed lead: {lead.email}"

    if db.was_contacted(lead.email, lead.brokerage_name):
        db.mark_lead_status(lead_id, "duplicate")
        db.log("skipped", "Lead was already contacted", lead.email)
        return f"Skipped duplicate contact: {lead.email}"

    message = render_email(agent_name=lead.agent_name, property_address=lead.property_address, settings=settings)

    if not dry_run and not settings.ready_to_send:
        db.log("error", "Sender details are incomplete; refusing to send")
        return "Refused to send because BUSINESS_PHONE, BUSINESS_ADDRESS, or GMAIL_SENDER is not production-ready."

    gmail_message_id = None
    if dry_run:
        LOGGER.info("DRY RUN: would email %s with subject %r", lead.email, message.subject)
    else:
        try:
            gmail_message_id = send_email(
                sender=settings.gmail_sender,
                to=lead.email,
                subject=message.subject,
                body=message.body,
                html_body=message.html_body,
                inline_logo_file=settings.logo_path,
                client_secret_file=settings.gmail_client_secret_file,
                token_file=settings.gmail_token_file,
            )
        except Exception as exc:
            safe = _safe_error(exc)
            LOGGER.error("Gmail send failed: %s", safe)
            db.log("error", "Gmail send failed", safe)
            return f"Gmail send failed: {safe}"

    db.record_sent(
        lead_id=lead_id,
        email=lead.email,
        brokerage_name=lead.brokerage_name,
        subject=message.subject,
        body=message.body,
        gmail_message_id=gmail_message_id,
        dry_run=dry_run,
    )
    db.mark_lead_status(lead_id, "validated" if dry_run else "sent")
    db.log("sent" if not dry_run else "dry_run", f"Processed outreach to {lead.email}", lead.listing_url)
    return f"{'Dry run recorded' if dry_run else 'Email sent'} for {lead.email}."


def run_once(settings: Settings, db: Database, *, dry_run: bool, use_existing: bool = False) -> str:
    db.init()
    lead_row = db.next_unsent_lead() if use_existing else None

    if lead_row is None:
        try:
            discovered = discover_one_lead(settings)
        except Exception as exc:
            safe = _safe_error(exc)
            LOGGER.error("Lead discovery failed: %s", safe)
            db.log("error", "Lead discovery failed", safe)
            return f"Lead discovery failed: {safe}"
        if not discovered:
            db.log("skipped", "No compliant lead discovered")
            return "No compliant lead discovered."
        lead_id = db.add_lead(discovered)
        if lead_id is None:
            db.log("skipped", "Lead already exists", discovered.listing_url)
            return "Discovered lead was already in the database."
        lead = discovered
    else:
        lead_id = int(lead_row["id"])
        lead = _row_to_lead(lead_row)

    return process_lead(settings, db, lead_id=lead_id, lead=lead, dry_run=dry_run)


def run_daily(settings: Settings, db: Database, *, dry_run: bool, limit: int | None = None) -> str:
    db.init()
    target = limit or settings.daily_send_limit
    results: list[str] = []

    existing_rows = db.next_unsent_leads(target)
    for lead_row in existing_rows:
        result = process_lead(settings, db, lead_id=int(lead_row["id"]), lead=_row_to_lead(lead_row), dry_run=dry_run)
        results.append(result)
        if len(results) >= target:
            break

    remaining = target - len(results)
    if remaining > 0:
        try:
            discovered_leads = discover_leads(settings, limit=remaining * 3)
        except Exception as exc:
            safe = _safe_error(exc)
            LOGGER.error("Lead discovery failed: %s", safe)
            db.log("error", "Lead discovery failed", safe)
            if not results:
                return f"Lead discovery failed: {safe}"
            results.append(f"Lead discovery failed after partial processing: {safe}")
            return "\n".join(results)

        for discovered in discovered_leads:
            if len(results) >= target:
                break
            lead_id = db.add_lead(discovered)
            if lead_id is None:
                db.log("skipped", "Lead already exists", discovered.listing_url)
                continue
            result = process_lead(settings, db, lead_id=lead_id, lead=discovered, dry_run=dry_run)
            results.append(result)

    if not results:
        db.log("skipped", "No compliant leads discovered")
        return "No compliant leads discovered."
    return "\n".join(results)
