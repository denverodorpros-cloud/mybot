# Denver Odor Pros Outreach Automation

Python automation that finds active home-sale leads, stores them in SQLite, and sends a limited number of compliant outreach emails through the Gmail API each day.

The project is intentionally conservative:

- Uses Brave Search API, or Google Programmable Search API for existing Google API customers, instead of scraping search result pages.
- Fetches listing/brokerage pages only from domains you explicitly allow.
- Checks robots.txt before every page fetch.
- Keeps suppression and send-history tables to avoid duplicate contacts.
- Defaults to dry-run mode.
- Includes CAN-SPAM-oriented footer content in every email.

## Setup

1. Create and activate a Python environment.

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Copy the environment template.

   ```powershell
   Copy-Item .env.example .env
   ```

3. Fill in `.env`.

   - `BUSINESS_ADDRESS` must be a real physical mailing address before sending. Use a business address, PO box, or commercial mailbox; do not use a personal home address unless you intentionally want it in every email.
   - `BUSINESS_PHONE` should be the Denver Odor Pros contact phone.
   - `SEARCH_PROVIDER=brave` and `BRAVE_SEARCH_API_KEY` are required for Brave discovery.
   - Add those same fetchable domains to `ALLOWED_FETCH_DOMAINS`.

4. Configure Gmail API OAuth.

   - In Google Cloud Console, enable the Gmail API.
   - Create OAuth client credentials for a desktop app.
   - Save the JSON file to `secrets/gmail_client_secret.json`.
   - The first non-dry-run send will open the OAuth browser flow and save `secrets/gmail_token.json`.
   - The authenticated account should be `denverodorpros@gmail.com`.

5. Initialize the database.

   ```powershell
   python -m outreach_automation init-db
   ```

## Dry Run

Dry-run mode discovers and logs one candidate without sending email.

```powershell
python -m outreach_automation run-daily --dry-run
```

You can also test with a manual lead instead of live discovery:

```powershell
python -m outreach_automation add-lead `
  --property-address "123 Example St, Denver, CO" `
  --listing-url "https://example.com/listing/123" `
  --agent-name "Jane Agent" `
  --brokerage-name "Example Realty" `
  --email "jane@example-realty.com"

python -m outreach_automation run-daily --dry-run
```

## CSV Import

Use this when you have already found public business emails from approved sources.

CSV columns:

```csv
property_address,listing_url,agent_name,brokerage_name,email,source
```

Start from [templates/leads_template.csv](templates/leads_template.csv), then import:

```powershell
python -m outreach_automation import-csv path\to\leads.csv
python -m outreach_automation run-once --dry-run --use-existing
```

The importer skips duplicate listing URLs and incomplete rows. Sending still checks suppression and prior sent history.

## Sending

Before sending, confirm:

- `DRY_RUN=false`
- `BUSINESS_ADDRESS` is a real mailing address.
- `BUSINESS_PHONE` is filled in.
- The Gmail OAuth sender is `denverodorpros@gmail.com`.
- Your allowlisted source domains permit the intended use.

Then run:

```powershell
python -m outreach_automation run-daily --send
```

## Daily Schedule

Run the in-process scheduler:

```powershell
python -m outreach_automation schedule
```

It runs daily at `SCHEDULE_TIME` in `TIMEZONE`, defaulting to `12:20` `America/Denver`.

For production, prefer Windows Task Scheduler, systemd, cron, or a small hosted worker that starts:

```powershell
python -m outreach_automation run-daily --send
```

at 12:20 PM Mountain Time daily.

Set `DAILY_SEND_LIMIT=2` in `.env` to process two leads per daily run. Use `run-once` only for single-lead testing.

## Suppression

Add an email or brokerage/company to the suppression list:

```powershell
python -m outreach_automation suppress --email jane@example-realty.com --reason "STOP reply"
python -m outreach_automation suppress --company "Example Realty" --reason "Do not contact"
```

Any email containing `STOP` should be added to suppression before the next run.

## Compliance Notes

This code is a compliance aid, not legal advice. Use it only with public business contact emails and only with sources whose Terms allow your access pattern. Do not use personal emails unless they are clearly published as business contact emails. Keep volume at one email per day unless you have reviewed the legal and deliverability implications.
