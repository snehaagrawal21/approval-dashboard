#!/usr/bin/env python3
"""
sync_dashboard.py
==================
Pulls fresh data from Metabase and regenerates the Approval Matrix
Dashboard HTML file in place — same layout, same logic, same everything
you've been reviewing. This script's only job is to keep the data fresh.

WHAT IT DOES
1. Logs into Metabase's API using an API key.
2. Fetches every row of the "Approval Matrix Request - Updated" question.
3. Cleans and reshapes each row into the compact schema the dashboard
   expects, and verifies the retry-loop churn count against the full
   dataset (see VERIFIED CHURN below).
4. Swaps the embedded dataset inside your existing dashboard HTML file
   for the fresh one. Everything else in that file (styling, filters,
   KPI cards, and — importantly — every flag/threshold rule) is left
   completely untouched, because none of it lives in this script.

WHY NO FLAGS ARE COMPUTED HERE
Every red/yellow flag (credit shortfall, margin gap, overdue dues,
interest delay, payment-term risk downgrade, zero sign-off, stuck
pending, retry loop) is computed **client-side**, inside the dashboard's
own JavaScript, straight from the raw fields this script outputs below.
That's deliberate: keeping the business rules in exactly one place (the
HTML file) means there's nothing here that can quietly drift out of
sync with what the dashboard actually shows. If a threshold or rule
ever needs to change, it changes in the HTML file — this script doesn't
need to be touched, and doesn't need redeploying.
The one exception is "verified churn" below, which genuinely has to
happen here because it requires cross-referencing every row against
every other row.

VERIFIED CHURN (retry-loop detection)
Whenever a request fails an automatic check, the system discards it and
creates a fresh one — the request's `message` field lists the IDs of
those earlier attempts in parentheses, e.g. "... (CADjR1d-29766) ...".
Older message formats don't embed IDs at all. Rather than trust the
text at face value, this script extracts every referenced ID and looks
each one up directly in the full dataset, only counting it if that ID
genuinely exists there with status INVALID. This is what "verified"
means — a text-only count would over- or under-count depending on
message format and phrasing.
  - `ch`   = the verified count (used by the dashboard's retry-loop flag)
  - `pids` = the verified IDs themselves (used for the "prior attempts"
             drill-down when you click a retry-loop row)

SETUP (one-time)
1. In Metabase: Settings (gear icon, top right) -> Admin Settings ->
   Authentication -> API Keys -> Create API Key. Copy it.
2. Find your card/question ID: open "Approval Matrix Request - Updated"
   in Metabase, the ID is the number in the URL, e.g.
   https://analytics.metalbook.app/question/784-approval-matrix-request-updated
                                                ^^^ that number
3. Fill in the four values under CONFIG below (or set them as
   environment variables of the same name — recommended for CI/CD,
   see the GitHub Actions example at the bottom of this file).
4. pip install requests pandas
5. Run once by hand to confirm it works:
     python sync_dashboard.py
6. Schedule it (see the GitHub Actions workflow further down, or any
   cron / scheduled task that runs this file periodically).

WHAT IT NEEDS EVERY RUN
- METABASE_URL       e.g. "https://analytics.metalbook.app"
- METABASE_API_KEY   the key from step 1
- METABASE_CARD_ID   the number from step 2
- DASHBOARD_HTML     path to the dashboard HTML file to update
  (start from any previously published copy of the dashboard — the
  script only replaces the embedded data, never the design or logic)
"""

import os
import re
import json
import math
import sys
from datetime import datetime, timezone

import requests
import pandas as pd

# ============================== CONFIG ==============================
# Fill these in, or set as environment variables (env vars win if set).
METABASE_URL = os.environ.get("METABASE_URL", "https://analytics.metalbook.app")
METABASE_API_KEY = os.environ.get("METABASE_API_KEY", "PASTE_YOUR_API_KEY_HERE")
METABASE_CARD_ID = os.environ.get("METABASE_CARD_ID", "784")
DASHBOARD_HTML = os.environ.get("DASHBOARD_HTML", "Approval_Matrix_Dashboard.html")
# ======================================================================


def fetch_metabase_data(base_url: str, api_key: str, card_id: str) -> pd.DataFrame:
    """Pull every row of the given Metabase question as a DataFrame."""
    url = f"{base_url}/api/card/{card_id}/query/json"
    headers = {"x-api-key": api_key}
    print(f"Fetching data from {url} ...")
    resp = requests.post(url, headers=headers, timeout=120)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise RuntimeError(
            "Metabase returned 0 rows — check the card ID and that the "
            "question isn't filtered down to nothing."
        )
    df = pd.DataFrame(rows)
    print(f"Fetched {len(df):,} rows, {len(df.columns)} columns.")
    return df


def num(series: pd.Series) -> pd.Series:
    """Strip commas/currency formatting and convert to float."""
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False), errors="coerce"
    )


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean and reshape the raw Metabase rows into the fields the dashboard
    needs. No flags or thresholds are decided here — see the module
    docstring for why. The only non-trivial work is verified churn
    (retry-loop detection), which has to happen here because it requires
    cross-referencing every row against the full dataset.
    """
    df = df.copy()

    df["required_credit_limit_n"] = num(df.get("required_credit_limit", pd.Series(dtype=object)))
    df["available_credit_limit_n"] = num(df.get("available_credit_limit", pd.Series(dtype=object)))
    df["Shortfall_n"] = num(df.get("Shortfall", pd.Series(dtype=object)))
    df["required_margin_n"] = num(df.get("required_margin", pd.Series(dtype=object)))
    df["CM_margin_n"] = num(df.get("CM_margin", pd.Series(dtype=object)))
    df["margin_gap_n"] = num(df.get("margin_gap", pd.Series(dtype=object)))
    df["overdue_amount_n"] = num(df.get("overdue_amount", pd.Series(dtype=object)))
    df["PO_amount_n"] = num(df.get("PO_amount", pd.Series(dtype=object)))
    df["avg_delay_n"] = num(df.get("avg_delay", pd.Series(dtype=object)))

    df["requested_at_dt"] = pd.to_datetime(
        df["requested_at"], errors="coerce", utc=True, format="mixed"
    )
    now = pd.Timestamp.now(tz="UTC")
    df["age_days"] = ((now - df["requested_at_dt"]).dt.total_seconds() / 86400).round(1)

    def parse_members(ms):
        if pd.isna(ms):
            return []
        return [p.strip().upper() for p in str(ms).split(",")]

    parsed = df.get("member_status", pd.Series(dtype=object)).apply(parse_members)
    df["n_members"] = parsed.apply(len)
    df["n_approved_members"] = parsed.apply(lambda l: sum(1 for x in l if x == "APPROVED"))

    # --- Verified churn / retry-loop detection ---------------------------
    # Extract every ID the message text claims was "marked Invalid", then
    # actually look each one up in the full dataset and only count it if
    # it's really there with status Invalid. Older message formats with no
    # ID embedded can't be verified, so they correctly count as 0 here,
    # even if the text still claims prior failures.
    id_to_status = dict(zip(df["credit_approval_id"], df["status"]))

    def extract_verified_ids(msg):
        if pd.isna(msg):
            return []
        ids = re.findall(r"\(([^)]+)\)", str(msg))
        return [i for i in ids if id_to_status.get(i) == "INVALID"]

    df["prior_ids"] = df.get("message", pd.Series(dtype=object)).apply(extract_verified_ids)
    df["churn_count"] = df["prior_ids"].apply(len)

    return df


def r2(v):
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f):
            return None
        return round(f, 1)
    except (TypeError, ValueError):
        return v


def clean_str(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v)
    return None if s.lower() == "nan" else s


def build_compact_json(df: pd.DataFrame) -> str:
    """
    Same short-key schema the dashboard's JavaScript expects — raw data
    only. The dashboard computes every flag itself from these fields on
    load; nothing here is pre-flagged.
    """
    short = []
    for _, d in df.iterrows():
        short.append(
            {
                "id": clean_str(d.get("approval_request_id")),
                "rid": clean_str(d.get("reference_id")),        # Enquiry ID
                "caid": clean_str(d.get("credit_approval_id")),  # Approval Request ID
                "org": clean_str(d.get("organisation_name")),
                "cat": clean_str(d.get("approval_type")),
                "st": clean_str(d.get("status")),
                "rq": clean_str(d.get("requested_at")),
                "age": r2(d.get("age_days")),
                "ttd": r2(d.get("turnaround_days")),
                "rcl": r2(d.get("required_credit_limit_n")),
                "acl": r2(d.get("available_credit_limit_n")),
                "sf": r2(d.get("Shortfall_n")),
                "rm": r2(d.get("required_margin_n")),
                "cmm": r2(d.get("CM_margin_n")),
                "mg": r2(d.get("margin_gap_n")),
                "od": r2(d.get("overdue_amount_n")),
                "ods": clean_str(d.get("overdue_amount_status")),
                "po": r2(d.get("PO_amount_n")),
                "sup": clean_str(d.get("supplier_name")),
                "reqby": clean_str(d.get("requested_by_full_name")),
                "appr": clean_str(d.get("member_full_name")),
                "apst": clean_str(d.get("member_status")),
                "napr": int(d.get("n_approved_members", 0)),
                "nmem": int(d.get("n_members", 0)),
                "ch": int(d.get("churn_count", 0) or 0),
                "pids": list(d.get("prior_ids") or []),
                "ept": clean_str(d.get("enquiry_payment_term")),
                "opt": clean_str(d.get("org_payment_term")),
                "ir": r2(d.get("interest_received")),
                "delay": r2(d.get("avg_delay")),
            }
        )
    txt = json.dumps(short, separators=(",", ":"))
    assert "NaN" not in txt, "NaN leaked into the JSON — check for unhandled nulls above"
    return txt


def update_dashboard_html(html_path: str, data_json: str) -> None:
    """Swap the embedded `const DATA = [...]` array for the fresh one,
    and bump the header's snapshot date + total counts. Everything else
    in the file (CSS, layout, filter logic, flag definitions) is left
    completely untouched."""
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    pattern = re.compile(r"const DATA = (\[.*?\]);\n", re.S)
    if not pattern.search(html):
        raise RuntimeError(
            f"Couldn't find 'const DATA = [...]' inside {html_path}. "
            "Make sure DASHBOARD_HTML points at a real copy of the dashboard."
        )
    html = pattern.sub(f"const DATA = {data_json};\n", html, count=1)

    today_str = datetime.now(timezone.utc).strftime("%d %b %Y")
    html = re.sub(r"snapshot as of \d{1,2} \w{3} \d{4}", f"snapshot as of {today_str}", html)

    total = data_json.count('"id":')
    orgs = len(set(re.findall(r'"org":"([^"]*)"', data_json)))
    html = re.sub(
        r"[\d,]+ requests · [\d,]+ organisations",
        f"{total:,} requests · {orgs:,} organisations",
        html,
    )

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Updated {html_path}: {total:,} requests, {orgs:,} organisations, snapshot {today_str}.")


def main():
    missing = [
        name
        for name, val in [
            ("METABASE_API_KEY", METABASE_API_KEY),
            ("METABASE_CARD_ID", METABASE_CARD_ID),
        ]
        if not val or val.startswith("PASTE_")
    ]
    if missing:
        print(f"Missing config: {', '.join(missing)}. Fill in CONFIG at the top of this "
              f"file, or set them as environment variables.", file=sys.stderr)
        sys.exit(1)

    raw = fetch_metabase_data(METABASE_URL, METABASE_API_KEY, METABASE_CARD_ID)
    cleaned = clean_dataframe(raw)
    data_json = build_compact_json(cleaned)
    update_dashboard_html(DASHBOARD_HTML, data_json)
    print("Done.")


if __name__ == "__main__":
    main()


# =====================================================================
# OPTIONAL: GitHub Actions workflow to run this daily.
# Save as .github/workflows/sync-dashboard.yml in a repo that also
# contains sync_dashboard.py and the dashboard HTML file. Add
# METABASE_API_KEY and METABASE_CARD_ID as repo Settings -> Secrets.
# =====================================================================
"""
name: Sync Approval Matrix Dashboard

on:
  schedule:
    - cron: "30 4 * * *"   # daily at 04:30 UTC (10:00 AM IST) — adjust as needed
  workflow_dispatch: {}     # lets you also trigger it manually

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install requests pandas
      - run: python sync_dashboard.py
        env:
          METABASE_URL: https://analytics.metalbook.app
          METABASE_API_KEY: ${{ secrets.METABASE_API_KEY }}
          METABASE_CARD_ID: ${{ secrets.METABASE_CARD_ID }}
          DASHBOARD_HTML: Approval_Matrix_Dashboard.html
      - name: Commit updated dashboard
        run: |
          git config user.name "dashboard-bot"
          git config user.email "actions@github.com"
          git add Approval_Matrix_Dashboard.html
          git commit -m "Auto-sync dashboard data" || echo "No changes"
          git push
      # If you're hosting via GitHub Pages, that push is enough —
      # Pages redeploys automatically. If hosting elsewhere (S3,
      # Netlify, etc.) add a deploy step here instead of git push.
"""
