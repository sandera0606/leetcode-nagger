"""Google Sheets reads via a service account."""

from __future__ import annotations

import json
import sys

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import env

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# The key file spans many lines, and `.env` only keeps a multi-line value
# together if the whole thing is quoted — the single commonest way to get a
# half-loaded credential.
_MULTILINE_HINT = (
    "Paste the entire key file Google gave you, braces included. In `.env` a\n"
    "multi-line value must be wrapped in single quotes:\n"
    "\n"
    "    GOOGLE_SERVICE_ACCOUNT_JSON='{\n"
    '      "type": "service_account",\n'
    "      ...\n"
    "    }'\n"
    "\n"
    "Without the quotes only the first line is read. In GitHub Actions Secrets\n"
    "no quoting is needed — paste the raw file."
)


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
            f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON ({exc}).\n"
            f"{_MULTILINE_HINT}"
        )
    if not isinstance(info, dict):
        sys.exit(
            "GOOGLE_SERVICE_ACCOUNT_JSON parsed, but it isn't an object — the key "
            f"file is a single {{...}} block.\n{_MULTILINE_HINT}"
        )
    # Valid JSON that isn't a key file gets a raw MalformedError from google-auth
    # otherwise, which names the missing fields but not the actual cause.
    missing = [k for k in ("client_email", "token_uri", "private_key") if not info.get(k)]
    if missing:
        sys.exit(
            f"GOOGLE_SERVICE_ACCOUNT_JSON parsed, but it's missing: {', '.join(missing)}.\n"
            "That usually means only part of the key file made it into the variable.\n"
            f"{_MULTILINE_HINT}"
        )
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def service_account_email() -> str:
    """The `client_email` from the key, for error messages. Best-effort."""
    try:
        return json.loads(env("GOOGLE_SERVICE_ACCOUNT_JSON")).get("client_email", "")
    except (json.JSONDecodeError, AttributeError, TypeError):
        return ""


def _api_failure(exc: HttpError, sheet_id: str) -> str:
    """Turn a Google API error into something you can act on.

    A raw HttpError traceback is the first thing most people setting this up
    will see, and "The caller does not have permission" doesn't hint that the
    fix is a Share dialog.
    """
    status = getattr(exc.resp, "status", None)
    if status == 403:
        who = service_account_email()
        target = f"\n\n    {who}\n\n" if who else " the service account's client_email "
        return (
            "Google won't let the service account open that spreadsheet (403).\n"
            f"Open the sheet, click Share, and add:{target}"
            "Viewer access is enough. If you've already shared it, check that the\n"
            "Sheets API is enabled on that service account's Google Cloud project."
        )
    if status == 404:
        return (
            f"No spreadsheet with id {sheet_id!r} (404).\n"
            "SHEET_ID is the long string in the sheet's URL, between /d/ and /edit."
        )
    return f"Google Sheets API error ({status}): {exc}"


def fetch_gid(sheets, sheet_id: str, tab: str) -> str | None:
    """Numeric sheetId for a tab, so the message can deep-link to it."""
    if not tab:
        return None
    try:
        meta = sheets.spreadsheets().get(
            spreadsheetId=sheet_id,
            fields="sheets.properties(sheetId,title)",
        ).execute()
    except HttpError as exc:
        sys.exit(_api_failure(exc, sheet_id))
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
    try:
        resp = sheets.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=range_,
        ).execute()
    except HttpError as exc:
        sys.exit(_api_failure(exc, sheet_id))
    return resp.get("values", []) or []


def sheet_url(sheet_id: str, gid: str | None) -> str:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    return f"{url}#gid={gid}" if gid else url
