"""Google Sheets reads via a service account."""

from __future__ import annotations

import json
import sys

from google.oauth2 import service_account
from googleapiclient.discovery import build

from .config import env

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def build_client():
    """Build a Sheets client from GOOGLE_SERVICE_ACCOUNT_JSON.

    That env var holds the raw service-account key JSON — the file Google
    hands you when you create the key. Share the spreadsheet with the
    service account's `client_email` (Viewer is enough).
    """
    raw = env(
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        required=True,
        hint="the whole service-account key file, pasted as one value",
    )
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.exit(
            f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON ({exc}). Paste the "
            "entire key file contents, braces included."
        )
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def fetch_gid(sheets, sheet_id: str, tab: str) -> str | None:
    """Numeric sheetId for a tab, so the message can deep-link to it."""
    if not tab:
        return None
    meta = sheets.spreadsheets().get(
        spreadsheetId=sheet_id,
        fields="sheets.properties(sheetId,title)",
    ).execute()
    for sheet in meta.get("sheets", []) or []:
        props = sheet.get("properties", {}) or {}
        if props.get("title") == tab:
            sid = props.get("sheetId")
            return str(sid) if sid is not None else None
    titles = [
        (s.get("properties") or {}).get("title", "?")
        for s in meta.get("sheets", []) or []
    ]
    sys.exit(
        f"No tab named {tab!r} in that spreadsheet. Tabs found: "
        f"{', '.join(titles)}. Fix `sheet.tab` in config.yml."
    )


def fetch_rows(sheets, sheet_id: str, tab: str) -> list[list[str]]:
    range_ = f"'{tab}'!A:Z" if tab else "A:Z"
    resp = sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=range_,
    ).execute()
    return resp.get("values", []) or []


def sheet_url(sheet_id: str, gid: str | None) -> str:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    return f"{url}#gid={gid}" if gid else url
