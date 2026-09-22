#!/usr/bin/env python3
"""
sync_dashboard.py
==================
Pulls fresh data from Metabase and regenerates the Approval Matrix
Management Dashboard HTML file in place — same flags, same logic,
same layout as the one you've been reviewing.

WHAT IT DOES
1. Logs into Metabase's API using an API key
2. Fetches every row of the "Approval Matrix Request - Updated" question
3. Recomputes every flag (credit overrides, margin overrides, overdue
   overrides, zero sign-off, retry-loop churn, PO-vs-credit shortfall,
   auto-approval rule checks, stuck-pending, etc.)
4. Swaps the embedded dataset inside your existing dashboard HTML file
   for the fresh one — everything else (styling, filters, click
   behaviour) stays exactly as-is, because it lives in the HTML file
   itself, not in this script.

SETUP (one-time)
1. In Metabase: Settings (gear icon, top right) -> Admin Settings ->
   Authentication -> API Keys -> Create API Key. Copy it.
2. Find your card/question ID: open "Approval Matrix Request - Updated"
   in Metabase, the ID is the number in the URL, e.g.
   https://analytics.metalbook.app/question/842-approval-matrix-request-updated
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


def build_flagged_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Reproduce every transform and flag used by the dashboard:
      f1  credit limit overridden (manual approval despite shortfall)
      f2  margin overridden (manual approval despite unmet requirement)
      f3  overdue approved despite open dues
      f4  overdue wrongly auto-approved (auto-approved despite dues)
      f5  stuck pending 14+ days
      f6  same request stuck in a retry loop (5+ recreations)
      f8  zero approvers actually signed off, yet marked Approved
      f9  interest payment approved despite 10+ day unpaid delay
      f10 supplier PO approved despite a credit shortfall on the same enquiry
      f11 credit limit auto-approval rule check (should always be 0)
      f12 margin auto-approval rule check (should always be 0)
    Note: f7 (payment type mismatch) is intentionally computed in the
    dashboard's own JavaScript from ept/opt at load time, not here —
    that's what lets the type-only matching rule live in one place.
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
    df["total_active_PO_amount_n"] = num(df.get("total_active_PO_amount", pd.Series(dtype=object)))

    df["requested_at_dt"] = pd.to_datetime(
        df["requested_at"], errors="coerce", utc=True, format="mixed"
    )
    now = pd.Timestamp.now(tz="UTC")
    df["age_days"] = ((now - df["requested_at_dt"]).dt.total_seconds() / 86400).round(1)

    df["churn_count"] = df.get("message", pd.Series(dtype=object)).fillna("").str.count(
        "previous approval"
    )

    def parse_members(ms):
        if pd.isna(ms):
            return []
        return [p.strip().upper() for p in str(ms).split(",")]

    parsed = df.get("member_status", pd.Series(dtype=object)).apply(parse_members)
    df["n_members"] = parsed.apply(len)
    df["n_approved_members"] = parsed.apply(lambda l: sum(1 for x in l if x == "APPROVED"))

    approved_like = df["status"].isin(["APPROVED", "AUTO_APPROVED"])

    df["flag_credit_override"] = (
        (df["approval_type"] == "CREDIT_LIMIT")
        & (df["status"] == "APPROVED")
        & (df["Shortfall_n"] > 0)
    )
    df["flag_margin_override"] = (
        (df["approval_type"] == "MARGIN")
        & (df["status"] == "APPROVED")
        & (df["margin_gap_n"] > 0)
    )
    df["flag_overdue_override"] = (
        (df["approval_type"] == "OVERDUE")
        & approved_like
        & (df["overdue_amount_status"] == "Due")
    )
    df["flag_overdue_anomaly"] = (
        (df["approval_type"] == "OVERDUE")
        & (df["status"] == "AUTO_APPROVED")
        & (df["overdue_amount_status"] == "Due")
    )
    df["flag_stuck_pending"] = (df["status"] == "PENDING") & (df["age_days"] > 14)
    df["flag_high_churn"] = df["churn_count"] >= 5
    df["flag_zero_signoff"] = (
        (df["status"] == "APPROVED") & (df["n_members"] > 0) & (df["n_approved_members"] == 0)
    )
    df["flag_interest_delay_approved"] = (
        (df["approval_type"] == "INTEREST_PAYMENT")
        & (df.get("interest_received") != 1)
        & approved_like
        & (num(df.get("avg_delay", pd.Series(dtype=object))) > 10)
    )
    df["flag_credit_wrong_auto"] = (
        (df["approval_type"] == "CREDIT_LIMIT")
        & (df["status"] == "AUTO_APPROVED")
        & (df["required_credit_limit_n"] > df["available_credit_limit_n"])
    )
    df["flag_margin_wrong_auto"] = (
        (df["approval_type"] == "MARGIN")
        & (df["status"] == "AUTO_APPROVED")
        & (df["required_margin_n"] >= df["CM_margin_n"])
    )

    # f10 + linked shortfall: cross-reference each Supplier PO against the
    # Credit Limit request for the SAME enquiry (reference_id), using the
    # latest state of each so churned/recreated rows don't double count.
    latest = df.sort_values("requested_at_dt").groupby(
        ["reference_id", "approval_type"], dropna=False
    ).tail(1)
    cl = latest[latest["approval_type"] == "CREDIT_LIMIT"][
        ["reference_id", "required_credit_limit_n", "available_credit_limit_n"]
    ].copy()
    cl["linked_shortfall"] = (
        cl["required_credit_limit_n"] - cl["available_credit_limit_n"]
    ).clip(lower=0)
    shortfall_map = dict(zip(cl["reference_id"], cl["linked_shortfall"]))
    req_map = dict(zip(cl["reference_id"], cl["required_credit_limit_n"]))
    avail_map = dict(zip(cl["reference_id"], cl["available_credit_limit_n"]))

    def po_shortfall(row):
        if row["approval_type"] != "SUPPLIER_PO" or row["status"] != "APPROVED":
            return False
        req = req_map.get(row["reference_id"])
        avail = avail_map.get(row["reference_id"])
        if req is None or avail is None or pd.isna(req) or pd.isna(avail):
            return False
        return req > avail

    df["flag_po_credit_shortfall"] = df.apply(po_shortfall, axis=1)
    df["linked_shortfall"] = df.apply(
        lambda r: shortfall_map.get(r["reference_id"])
        if r["approval_type"] == "SUPPLIER_PO"
        else None,
        axis=1,
    )

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
    """Same short-key schema the dashboard's JavaScript expects."""
    short = []
    for _, d in df.iterrows():
        short.append(
            {
                "id": clean_str(d.get("approval_request_id")),
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
                "tpo": r2(d.get("total_active_PO_amount_n")),
                "lsf": r2(d.get("linked_shortfall")),
                "sup": clean_str(d.get("supplier_name")),
                "reqby": clean_str(d.get("requested_by_full_name")),
                "appr": clean_str(d.get("member_full_name")),
                "apst": clean_str(d.get("member_status")),
                "napr": int(d.get("n_approved_members", 0)),
                "nmem": int(d.get("n_members", 0)),
                "ch": int(d.get("churn_count", 0) or 0),
                "isA": int(d.get("Is Approved", 0) or 0),
                "isD": int(d.get("Is Decided", 0) or 0),
                "ept": clean_str(d.get("enquiry_payment_term")),
                "opt": clean_str(d.get("org_payment_term")),
                "ir": r2(d.get("interest_received")),
                "delay": r2(d.get("avg_delay")),
                "f1": bool(d.get("flag_credit_override")),
                "f2": bool(d.get("flag_margin_override")),
                "f3": bool(d.get("flag_overdue_override")),
                "f4": bool(d.get("flag_overdue_anomaly")),
                "f5": bool(d.get("flag_stuck_pending")),
                "f6": bool(d.get("flag_high_churn")),
                "f7": False,  # recomputed client-side from ept/opt — see docstring
                "f8": bool(d.get("flag_zero_signoff")),
                "f9": bool(d.get("flag_interest_delay_approved")),
                "f10": bool(d.get("flag_po_credit_shortfall")),
                "f11": bool(d.get("flag_credit_wrong_auto")),
                "f12": bool(d.get("flag_margin_wrong_auto")),
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
    flagged = build_flagged_dataframe(raw)
    data_json = build_compact_json(flagged)
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
    - cron: "0 3 * * *"   # daily at 03:00 UTC — adjust as needed
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
