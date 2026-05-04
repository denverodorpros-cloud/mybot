from __future__ import annotations

import argparse
import csv
import logging
import sys

from .config import load_settings
from .db import Database
from .models import Lead
from .runner import run_daily, run_once
from .scheduler import start_scheduler


CSV_FIELDS = ["property_address", "listing_url", "agent_name", "brokerage_name", "email", "source"]


def import_leads_csv(path: str, db: Database) -> tuple[int, int]:
    added = 0
    skipped = 0
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [field for field in CSV_FIELDS[:-1] if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")

        for row in reader:
            if not any((value or "").strip() for value in row.values()):
                continue
            lead = Lead(
                property_address=row["property_address"].strip(),
                listing_url=row["listing_url"].strip(),
                agent_name=row["agent_name"].strip(),
                brokerage_name=row["brokerage_name"].strip(),
                email=row["email"].strip(),
                source=(row.get("source") or "csv").strip() or "csv",
            )
            if not all([lead.property_address, lead.listing_url, lead.agent_name, lead.brokerage_name, lead.email]):
                skipped += 1
                continue
            if db.add_lead(lead):
                added += 1
            else:
                skipped += 1
    return added, skipped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Denver Odor Pros compliant outreach automation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Create or migrate the SQLite database")

    run_once_parser = subparsers.add_parser("run-once", help="Discover and process one lead")
    mode = run_once_parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Record what would be sent without sending")
    mode.add_argument("--send", action="store_true", help="Send through Gmail API")
    run_once_parser.add_argument("--use-existing", action="store_true", help="Use the oldest unsent lead already in SQLite")

    daily_parser = subparsers.add_parser("run-daily", help="Process up to DAILY_SEND_LIMIT leads")
    daily_mode = daily_parser.add_mutually_exclusive_group()
    daily_mode.add_argument("--dry-run", action="store_true", help="Record what would be sent without sending")
    daily_mode.add_argument("--send", action="store_true", help="Send through Gmail API")
    daily_parser.add_argument("--limit", type=int, help="Override DAILY_SEND_LIMIT for this run")

    add_lead = subparsers.add_parser("add-lead", help="Manually add a compliant lead")
    add_lead.add_argument("--property-address", required=True)
    add_lead.add_argument("--listing-url", required=True)
    add_lead.add_argument("--agent-name", required=True)
    add_lead.add_argument("--brokerage-name", required=True)
    add_lead.add_argument("--email", required=True)
    add_lead.add_argument("--source", default="manual")

    import_csv = subparsers.add_parser("import-csv", help="Import compliant public business leads from CSV")
    import_csv.add_argument("path", help="CSV path with property_address, listing_url, agent_name, brokerage_name, email")

    suppress = subparsers.add_parser("suppress", help="Add an email or company to the suppression list")
    suppress.add_argument("--email")
    suppress.add_argument("--company")
    suppress.add_argument("--reason", required=True)

    subparsers.add_parser("schedule", help="Run the daily APScheduler loop")
    return parser


def main(argv: list[str] | None = None) -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    db = Database(settings.database_path)
    args = build_parser().parse_args(argv)

    if args.command == "init-db":
        db.init()
        print(f"Initialized database at {settings.database_path}")
        return

    if args.command == "run-once":
        dry_run = True if args.dry_run else False if args.send else settings.dry_run
        print(run_once(settings, db, dry_run=dry_run, use_existing=args.use_existing))
        return

    if args.command == "run-daily":
        dry_run = True if args.dry_run else False if args.send else settings.dry_run
        print(run_daily(settings, db, dry_run=dry_run, limit=args.limit))
        return

    if args.command == "add-lead":
        db.init()
        lead_id = db.add_lead(
            Lead(
                property_address=args.property_address,
                listing_url=args.listing_url,
                agent_name=args.agent_name,
                brokerage_name=args.brokerage_name,
                email=args.email,
                source=args.source,
            )
        )
        print(f"Added lead #{lead_id}" if lead_id else "Lead already exists")
        return

    if args.command == "import-csv":
        db.init()
        try:
            added, skipped = import_leads_csv(args.path, db)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2)
        print(f"Imported {added} lead(s), skipped {skipped}.")
        return

    if args.command == "suppress":
        if not args.email and not args.company:
            print("Provide --email or --company.", file=sys.stderr)
            raise SystemExit(2)
        db.init()
        db.add_suppression(args.email, args.company, args.reason)
        print("Suppression saved")
        return

    if args.command == "schedule":
        db.init()
        start_scheduler(settings, db)
        return
