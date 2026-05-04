from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import Lead


SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_address TEXT NOT NULL,
    listing_url TEXT NOT NULL UNIQUE,
    agent_name TEXT NOT NULL,
    brokerage_name TEXT NOT NULL,
    email TEXT NOT NULL,
    normalized_email TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_normalized_email ON leads(normalized_email);

CREATE TABLE IF NOT EXISTS sent_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER,
    normalized_email TEXT NOT NULL,
    brokerage_name TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    gmail_message_id TEXT,
    dry_run INTEGER NOT NULL DEFAULT 0,
    sent_at TEXT NOT NULL,
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sent_email_once
ON sent_emails(normalized_email)
WHERE dry_run = 0;
CREATE INDEX IF NOT EXISTS idx_sent_company ON sent_emails(LOWER(brokerage_name));

CREATE TABLE IF NOT EXISTS suppression_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    normalized_email TEXT,
    company_name TEXT,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (normalized_email IS NOT NULL OR company_name IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_suppression_email
ON suppression_list(normalized_email)
WHERE normalized_email IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_suppression_company
ON suppression_list(LOWER(company_name))
WHERE company_name IS NOT NULL;

CREATE TABLE IF NOT EXISTS run_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_email(email: str) -> str:
    return email.strip().lower()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def log(self, event_type: str, message: str, details: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO run_logs(event_type, message, details, created_at) VALUES (?, ?, ?, ?)",
                (event_type, message, details, utc_now()),
            )

    def add_lead(self, lead: Lead) -> int | None:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO leads(
                    property_address, listing_url, agent_name, brokerage_name, email,
                    normalized_email, source, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead.property_address,
                    lead.listing_url,
                    lead.agent_name,
                    lead.brokerage_name,
                    lead.email,
                    normalize_email(lead.email),
                    lead.source,
                    now,
                    now,
                ),
            )
            return cursor.lastrowid or None

    def add_suppression(self, email: str | None, company: str | None, reason: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO suppression_list(normalized_email, company_name, reason, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (normalize_email(email) if email else None, company.strip() if company else None, reason, utc_now()),
            )

    def is_suppressed(self, email: str, company: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM suppression_list
                WHERE normalized_email = ?
                   OR (company_name IS NOT NULL AND LOWER(company_name) = LOWER(?))
                LIMIT 1
                """,
                (normalize_email(email), company.strip()),
            ).fetchone()
            return row is not None

    def was_contacted(self, email: str, company: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM sent_emails
                WHERE dry_run = 0
                  AND (
                    normalized_email = ?
                    OR LOWER(brokerage_name) = LOWER(?)
                  )
                LIMIT 1
                """,
                (normalize_email(email), company.strip()),
            ).fetchone()
            return row is not None

    def next_unsent_lead(self) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM leads
                WHERE status IN ('new', 'validated')
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()

    def next_unsent_leads(self, limit: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM leads
                WHERE status IN ('new', 'validated')
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def mark_lead_status(self, lead_id: int, status: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE leads SET status = ?, updated_at = ? WHERE id = ?", (status, utc_now(), lead_id))

    def record_sent(
        self,
        lead_id: int,
        email: str,
        brokerage_name: str,
        subject: str,
        body: str,
        gmail_message_id: str | None,
        dry_run: bool,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sent_emails(
                    lead_id, normalized_email, brokerage_name, subject, body,
                    gmail_message_id, dry_run, sent_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (lead_id, normalize_email(email), brokerage_name, subject, body, gmail_message_id, int(dry_run), utc_now()),
            )
