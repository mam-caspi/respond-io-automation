#!/usr/bin/env python3
"""
update_usernames.py
-------------------
Reads all Respond.io contacts, finds the Instagram username from the first
outgoing message ("from your Instagram page <username>"), and fills in the
custom field `username` for any contact where it is currently blank.

On each run, the script saves the highest contact ID it has seen to
`state.json`. The next run will automatically skip any contact with an ID
equal to or lower than that value, so only NEW contacts are processed.

Usage:
    python3 update_usernames.py --token YOUR_API_TOKEN

Optional flags:
    --limit N          contacts per page (1-99, default 50)
    --msg-limit N      messages per page (1-50, default 50)
    --state FILE       path to state JSON   (default: state.json)
    --log FILE         path to log file     (default: progress.log)
    --dry-run          scan & log but do NOT write to the API
    --full-scan        ignore saved state and process ALL contacts
"""

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests

BASE_URL = "https://api.respond.io/v2"
USERNAME_FIELD = "username"
IG_PATTERN = re.compile(
    r"from your Instagram page\s+([A-Za-z0-9_.]+)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_existing_username(contact: dict) -> Optional[str]:
    """Return the current value of the 'username' custom field, or None."""
    for cf in contact.get("custom_fields") or []:
        if cf.get("name") == USERNAME_FIELD:
            v = cf.get("value")
            return v if v else None
    return None


def api_get(session: requests.Session, url: str, params: dict = None) -> dict:
    """GET with simple retry logic."""
    for attempt in range(3):
        try:
            r = session.get(url, params=params, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 5))
                logging.warning(f"Rate limited, waiting {wait}s …")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            if attempt == 2:
                raise
            logging.warning(f"GET {url} failed ({exc}), retrying …")
            time.sleep(2)
    return {}


def api_post(session: requests.Session, url: str, body: dict, params: dict = None) -> dict:
    """POST with simple retry logic."""
    for attempt in range(3):
        try:
            r = session.post(url, json=body, params=params, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 5))
                logging.warning(f"Rate limited, waiting {wait}s …")
                time.sleep(wait)
                continue
            if not r.ok:
                logging.error(f"POST {url} → HTTP {r.status_code}: {r.text}")
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            if attempt == 2:
                raise
            logging.warning(f"POST {url} failed ({exc}), retrying …")
            time.sleep(2)
    return {}


def api_put(session: requests.Session, url: str, body: dict) -> dict:
    """PUT with simple retry logic."""
    for attempt in range(3):
        try:
            r = session.put(url, json=body, timeout=30)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 5))
                logging.warning(f"Rate limited, waiting {wait}s …")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            if attempt == 2:
                raise
            logging.warning(f"PUT {url} failed ({exc}), retrying …")
            time.sleep(2)
    return {}


# ---------------------------------------------------------------------------
# State helpers (tracks max contact ID seen across runs)
# ---------------------------------------------------------------------------

def load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {"max_contact_id": 0}


def save_state(path: Path, max_contact_id: int):
    path.write_text(json.dumps({"max_contact_id": max_contact_id}, indent=2))


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def list_contacts(session: requests.Session, limit: int):
    """Generator that yields contact dicts one at a time."""
    cursor_id = None
    page = 0
    while True:
        params = {"limit": limit}
        if cursor_id is not None:
            params["cursorId"] = cursor_id

        body = {"search": "", "filter": {"$and": []}, "timezone": "UTC"}
        data = api_post(session, f"{BASE_URL}/contact/list", body=body, params=params)

        items = data.get("items") or []
        page += 1
        logging.info(f"Fetched contact page {page} — {len(items)} contacts")

        for contact in items:
            yield contact

        next_url = (data.get("pagination") or {}).get("next")
        if not next_url or not items:
            break

        qs = parse_qs(urlparse(next_url).query)
        cursor_list = qs.get("cursorId", [])
        if not cursor_list:
            break
        cursor_id = int(cursor_list[0])


def find_instagram_username(session: requests.Session, contact_id: int, msg_limit: int) -> Optional[str]:
    """Scan the contact's messages for an Instagram page username."""
    cursor_id = None
    while True:
        params = {"limit": msg_limit}
        if cursor_id is not None:
            params["cursorId"] = cursor_id

        url = f"{BASE_URL}/contact/id:{contact_id}/message/list"
        data = api_get(session, url, params=params)

        items = data.get("items") or []
        for item in items:
            traffic = item.get("traffic", "")
            text = (item.get("message") or {}).get("text") or ""
            if traffic == "outgoing" and text:
                m = IG_PATTERN.search(text)
                if m:
                    return m.group(1)

        next_url = (data.get("pagination") or {}).get("next")
        if not next_url or not items:
            break

        qs = parse_qs(urlparse(next_url).query)
        cursor_list = qs.get("cursorId", [])
        if not cursor_list:
            break
        cursor_id = cursor_list[0]

    return None


def update_username(session: requests.Session, contact_id: int, username: str, dry_run: bool) -> bool:
    """Set the username custom field on a contact."""
    if dry_run:
        logging.info(f"  [DRY-RUN] Would update contact {contact_id} → username={username!r}")
        return True

    url = f"{BASE_URL}/contact/id:{contact_id}"
    body = {"custom_fields": [{"name": USERNAME_FIELD, "value": username}]}
    result = api_put(session, url, body)
    return "contactId" in result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fill missing Respond.io @username fields from Instagram messages.")
    parser.add_argument("--token", required=True, help="Respond.io API Bearer token")
    parser.add_argument("--limit", type=int, default=50, help="Contacts per page (max 99)")
    parser.add_argument("--msg-limit", type=int, default=50, help="Messages per page (max 50)")
    parser.add_argument("--state", default="state.json", help="State file path (tracks max contact ID)")
    parser.add_argument("--log", default="progress.log", help="Log file path")
    parser.add_argument("--dry-run", action="store_true", help="Do not write any changes to the API")
    parser.add_argument("--full-scan", action="store_true", help="Ignore saved state, process all contacts")
    args = parser.parse_args()

    # Logging setup
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(args.log),
            logging.StreamHandler(sys.stdout),
        ],
    )

    if args.dry_run:
        logging.info("=== DRY RUN MODE — no changes will be written ===")

    state_path = Path(args.state)
    state = load_state(state_path)
    min_id = 0 if args.full_scan else state.get("max_contact_id", 0)

    if min_id > 0:
        logging.info(f"New-contacts-only mode: skipping any contact with ID ≤ {min_id}")
    else:
        logging.info("Full scan mode: processing all contacts.")

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {args.token}"})

    processed = 0
    updated = 0
    skipped_old = 0
    skipped_has_username = 0
    not_found = 0
    max_seen_id = min_id

    try:
        for contact in list_contacts(session, args.limit):
            contact_id = contact.get("id") or contact.get("contactId")
            name = contact.get("name") or contact.get("fullName") or f"#{contact_id}"

            # Track highest ID seen this run
            if contact_id and contact_id > max_seen_id:
                max_seen_id = contact_id

            # Skip contacts already processed in a previous run
            if contact_id and contact_id <= min_id:
                skipped_old += 1
                continue

            processed += 1

            existing = get_existing_username(contact)
            if existing:
                logging.debug(f"Contact {contact_id} ({name}): username already set ({existing!r}), skipping.")
                skipped_has_username += 1
            else:
                logging.info(f"Contact {contact_id} ({name}): username is empty, scanning messages …")
                ig_username = find_instagram_username(session, contact_id, args.msg_limit)
                if ig_username:
                    success = update_username(session, contact_id, ig_username, args.dry_run)
                    if success:
                        logging.info(f"  ✓ Set username={ig_username!r}")
                        updated += 1
                    else:
                        logging.warning(f"  ✗ Update failed for contact {contact_id}")
                else:
                    logging.info(f"  — No Instagram username found in messages.")
                    not_found += 1

            if processed % 50 == 0:
                logging.info(f"--- Progress: {processed} new contacts checked, {updated} updated ---")

    except KeyboardInterrupt:
        logging.info("Interrupted by user.")
    finally:
        # Save the highest contact ID we saw so next run only picks up newer ones
        if not args.dry_run and max_seen_id > min_id:
            save_state(state_path, max_seen_id)
            logging.info(f"State saved: next run will skip contacts with ID ≤ {max_seen_id}")

        logging.info(
            f"\n=== DONE ===\n"
            f"  New contacts processed : {processed}\n"
            f"  Updated                : {updated}\n"
            f"  Already had username   : {skipped_has_username}\n"
            f"  No username in messages: {not_found}\n"
            f"  Skipped (old contacts) : {skipped_old}\n"
        )


if __name__ == "__main__":
    main()
