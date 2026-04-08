#!/usr/bin/env python3
"""
SEC EDGAR Rights Offering Tracker

Polls EDGAR full-text search for new rights offering filings and sends
SMS alerts via email-to-SMS carrier gateway.

Required environment variables:
  SMTP_HOST     - e.g. smtp.gmail.com
  SMTP_PORT     - e.g. 587 (default)
  SMTP_USER     - your Gmail address
  SMTP_PASS     - Gmail app password (not your account password)
  SMS_EMAIL     - your_number@tmomail.net
  EDGAR_AGENT   - "YourName your@email.com" (required by SEC)
"""

import json
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

import requests

EDGAR_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
STATE_FILE = Path(__file__).parent / "seen_filings.json"
CONFIG_FILE = Path(__file__).parent / "config.json"

# Customize these to narrow or broaden what you track
SEARCH_QUERY = '"rights"'
FORM_TYPES = "424B3"
LOOKBACK_DAYS = 2  # overlap prevents gaps if a run is skipped


def load_watchlist() -> list:
    if not CONFIG_FILE.exists():
        return []
    data = json.loads(CONFIG_FILE.read_text())
    return [name.lower() for name in data.get("watchlist", [])]


def matches_watchlist(company: str, watchlist: list) -> bool:
    if not watchlist:
        return True  # no filter — alert on everything
    company_lower = company.lower()
    return any(term in company_lower for term in watchlist)


def load_seen() -> set:
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text())
        return set(data)
    return set()


def save_seen(seen: set) -> None:
    STATE_FILE.write_text(json.dumps(sorted(seen), indent=2))


def search_edgar() -> list:
    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    params = {
        "q": SEARCH_QUERY,
        "forms": FORM_TYPES,
        "dateRange": "custom",
        "startdt": start_date,
        "enddt": end_date,
    }

    agent = os.environ.get("EDGAR_AGENT", "rights-offering-tracker contact@example.com")
    resp = requests.get(
        EDGAR_EFTS_URL,
        params=params,
        headers={"User-Agent": agent},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("hits", {}).get("hits", [])


def filing_url(adsh: str, cik: str) -> str:
    # adsh format: 0001234567-24-000001
    cik_int = str(int(cik))  # strip leading zeros
    clean = adsh.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{clean}/"


def parse_company(display_names: list) -> str:
    # display_names entries look like: "COMPANY NAME  (TICK)  (CIK 0001234567)"
    if not display_names:
        return "Unknown"
    raw = display_names[0]
    # Take everything before the first parenthetical
    return raw.split("(")[0].strip() or raw


def send_sms(subject: str, body: str) -> None:
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    sms_email = os.environ["SMS_EMAIL"]

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = sms_email

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)


def main() -> int:
    watchlist = load_watchlist()
    if watchlist:
        print(f"Watchlist: {len(watchlist)} name(s)")
    else:
        print("No watchlist — alerting on all rights offering filings")

    seen = load_seen()
    hits = search_edgar()

    new_count = 0
    for hit in hits:
        src = hit.get("_source", {})
        adsh = src.get("adsh", "")

        if not adsh or adsh in seen:
            continue

        company = parse_company(src.get("display_names", []))

        if not matches_watchlist(company, watchlist):
            seen.add(adsh)  # mark seen so we don't recheck it
            continue

        seen.add(adsh)
        new_count += 1

        form = src.get("form", "")
        date = src.get("file_date", "")
        cik = (src.get("ciks") or ["0"])[0]
        url = filing_url(adsh, cik)

        # Keep SMS short — carrier gateways truncate long messages
        subject = f"Rights Offering: {company[:50]}"
        body = f"{form} filed {date}\n{url}"

        print(f"  [{new_count}] {company} ({form}) on {date}")
        send_sms(subject, body)

    save_seen(seen)
    print(f"Done. {new_count} new filing(s) found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
