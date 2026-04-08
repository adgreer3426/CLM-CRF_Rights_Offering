#!/usr/bin/env python3
"""
SEC EDGAR Rights Offering Tracker

Polls data.sec.gov/submissions for 424B3 filings from specific funds
and sends SMS alerts via email-to-SMS carrier gateway.

Required environment variables:
  SMTP_HOST     - e.g. smtp.gmail.com
  SMTP_PORT     - e.g. 587 (default)
  SMTP_USER     - your Gmail address
  SMTP_PASS     - Gmail app password (not your account password)
  SMS_EMAIL     - your_number@tmomail.net
  EDGAR_AGENT   - "Your Name your@email.com" (required by SEC)
"""

import json
import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path

import requests

STATE_FILE = Path(__file__).parent / "seen_filings.json"
CONFIG_FILE = Path(__file__).parent / "config.json"

LOOKBACK_DAYS = 3
TARGET_FORM = "424B3"


def load_config() -> list:
    data = json.loads(CONFIG_FILE.read_text())
    return data["funds"]


def load_seen() -> set:
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(seen: set) -> None:
    STATE_FILE.write_text(json.dumps(sorted(seen), indent=2))


def get_recent_filings(cik: str, agent: str) -> list:
    """Fetch recent filings for a CIK from data.sec.gov/submissions."""
    cik_padded = cik.lstrip("0").zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    resp = requests.get(url, headers={"User-Agent": agent}, timeout=30)
    resp.raise_for_status()

    data = resp.json()
    recent = data.get("filings", {}).get("recent", {})

    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])

    cutoff = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    results = []
    for form, date, adsh in zip(forms, dates, accessions):
        if form == TARGET_FORM and date >= cutoff:
            results.append({"form": form, "date": date, "adsh": adsh})
    return results


def filing_url(cik: str, adsh: str) -> str:
    cik_int = str(int(cik))
    clean = adsh.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{clean}/"


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
    agent = os.environ.get("EDGAR_AGENT", "rights-offering-tracker contact@example.com")
    funds = load_config()
    seen = load_seen()

    print(f"Checking {len(funds)} fund(s) for {TARGET_FORM} filings...")

    new_count = 0
    for fund in funds:
        name = fund["name"]
        cik = fund["cik"]
        print(f"  {name} (CIK {cik})")

        filings = get_recent_filings(cik, agent)
        for f in filings:
            key = f["adsh"]
            if key in seen:
                continue

            seen.add(key)
            new_count += 1
            url = filing_url(cik, f["adsh"])

            subject = f"424B3: {name[:50]}"
            body = f"Filed {f['date']}\n{url}"

            print(f"    NEW: {f['form']} on {f['date']}")
            send_sms(subject, body)

    save_seen(seen)
    print(f"Done. {new_count} new filing(s) found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
