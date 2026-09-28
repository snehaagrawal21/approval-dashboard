# Approval Matrix — Automated Dashboard

**Live dashboard:** [https://snehaagrawal21.github.io/approval-dashboard/Approval_Matrix_Dashboard.html](https://snehaagrawal21.github.io/approval-dashboard/Approval_Matrix_Dashboard.html)

*Updates itself automatically every day at 10:00 AM IST. No one has to touch it.*

---

## What this is

A dashboard on top of the approval-workflow dataset — thousands of requests across six categories (Credit Limit, Margin, Overdue, Payment Terms, Interest Payment, Supplier PO) — that refreshes itself with zero human involvement.

It automatically finds and flags things like:
- Approvals that went through despite a real credit shortfall, margin gap, or unpaid dues
- Payment terms that quietly got riskier than what was required — and slipped through, sometimes with no one even reviewing it
- Requests marked "Approved" where nobody on record actually signed off
- The same request failing and being recreated over and over (verified against the database, not just guessed from the text) — a sign something's stuck, not just slow
- Requests that have been sitting unresolved for two weeks or more

Every number and flag is clickable and drills straight down to the exact requests behind it — Enquiry ID, Approval Request ID, who asked, who was supposed to approve it, who actually did. You can filter by category, organisation, requester, approver, status, date range, Enquiry ID, or Approval Request ID — any combination at once — and every click-through (a KPI card, an alert, a breakdown cell) is a step you can undo and redo with the **← Back / Forward →** buttons, not just a hard reset.

---

## The flow, in one picture

```
   Metabase                sync_dashboard.py                Approval_Matrix_Dashboard.html
 (where the raw   ──────▶   (pulls fresh raw data,   ──────▶   (the live dashboard —
  data lives)                nothing more)                      every flag & rule lives
                                     ▲                           here, computed live
                                     │                           in the browser)
                         sync-dashboard.yml
                        (tells it when to run)
```

Once a day, on its own: pull fresh raw data → drop it into the dashboard file → the dashboard works out every flag itself, live, the moment it's opened. No exports, no copy-pasting, no remembering to refresh it.

---

## What each file does, and how it actually works

### `Approval_Matrix_Dashboard.html`
This one file *is* the whole dashboard — filters, the 6 KPI cards, the flagged-issue alert cards, the category breakdown, the full request list (each row traceable back to its Enquiry ID and Approval Request ID), all of it, built right in. Near the bottom of the file sits a block holding every request's *raw* data. That block is the only part that changes day to day.

**Every flag and threshold is decided inside this file, in JavaScript, the moment it loads** — not precomputed anywhere upstream. That's deliberate: it means there is exactly one place where the business rules live. If a threshold ever needs to change, it changes here, and only here.

The current flag scheme, all computed from the raw fields:

| Flag | Condition |
|---|---|
| Zero sign-off | Status Approved, ≥1 approver listed, but none of them actually signed off |
| Credit Limit — Red / Yellow | Approved despite a shortfall: **>₹1L = Red, ₹0–1L = Yellow** |
| Margin — Red / Yellow | Approved despite the required margin not being met: **>₹1L gap = Red, ₹0–1L = Yellow** |
| Overdue — Red / Yellow | Approved (auto or manual) despite dues outstanding: **>₹1L = Red, ₹0–1L = Yellow** |
| Interest Payment — Red / Yellow | Not recorded as received, approved anyway: **delay >30 days = Red, 10–30 days = Yellow** |
| Payment Terms — Red / Yellow | Type doesn't match, **and** the organisation's actual term is genuinely riskier than what the enquiry required (Advance < LC/BG < POD < Credit) — a same-or-safer substitution is *not* flagged. Red if it slipped through auto-approval, Yellow if a reviewer approved it anyway |
| Stuck pending | Status Pending, sitting unresolved for 14+ days |
| Retry loop | Status Pending, and verified against the database as having failed and been recreated 5+ times |

Green ("nothing wrong") is never shown as a card — only real problems get one, red first.

### `sync_dashboard.py`
A script that runs once a day and does exactly one job: keep the data fresh. Each run:
1. Logs into Metabase with a stored key and pulls every row of the report
2. Cleans it up and verifies the retry-loop churn count — this is the one piece of logic that genuinely has to happen here, because it means cross-checking every request's message history against the *entire* dataset to confirm which prior attempts are real (an ID only counts if it's actually found elsewhere in the data with status Invalid — text alone isn't trusted)
3. Packages the result into the compact format the dashboard expects — raw fields only, no flags baked in
4. Opens the dashboard file and swaps in the new data block, leaving everything else — styling, flags, click behaviour — completely untouched

### `sync-dashboard.yml`
A short instruction file that tells GitHub: *"every day at 4:30 AM UTC (10:00 AM IST), start a computer, install what the script needs, run it, and save what it produces."* It also lets you trigger the same run manually anytime, which is how you'd test it before trusting it to run alone.

---

## Exactly what happens, every single day

1. **10:00 AM IST.** GitHub's own servers — not anyone's laptop — wake up and start the job.
2. A brand-new, temporary computer is created in the cloud, just for this one run. Python and two small tools get installed on it.
3. The script runs. Two secret values (the Metabase key, and the ID of the specific report to pull) are handed to it securely at that exact moment — never written into any file anyone can see.
4. It asks Metabase for the freshest data available.
5. It cleans it up and verifies the retry-loop churn count against the full dataset.
6. It opens the dashboard file, swaps in the new raw data, and updates the "snapshot as of" date and the total request/organisation counts at the top.
7. The updated file is saved back into the project, replacing yesterday's version.
8. The hosting service notices the file changed and republishes it automatically — no extra step needed.
9. The moment anyone opens the page, the dashboard's own JavaScript reads that fresh raw data and works out every flag itself, live.
10. The temporary computer from step 2 is thrown away. It existed for about 20–30 seconds, did its job, and is gone.

---

## Why each setting mattered

| Setting | What it's actually for |
|---|---|
| API key | A password just for this automation, so it can read data without anyone's personal login |
| Card / Report ID | Tells the script exactly which saved report to pull |
| Stored secrets, never typed into a visible file | Keeps credentials hidden even in a public project |
| Hosting turned on | Turns a plain file into an actual clickable website address |
| "Read and write" permission | Lets the automation save its own results back — without it, every run fails at the last step |
| The schedule | The clock — decides what time, every day, this happens without anyone watching |

---

## The result

One link, always current, that anyone in any department can open and immediately understand — what's happening, what needs a second look, and why — without a spreadsheet, a manual refresh, or someone explaining it to them.

**Live dashboard:** [https://snehaagrawal21.github.io/approval-dashboard/Approval_Matrix_Dashboard.html](https://snehaagrawal21.github.io/approval-dashboard/Approval_Matrix_Dashboard.html)

---

## One honest limitation

This runs on GitHub's free scheduler, which can occasionally start a few minutes later than the set time during busy periods — perfectly fine for a once-a-day dashboard refresh, but not something to rely on if a job ever needed to run at an exact second. For anything with that kind of precision requirement, a dedicated scheduler (like a cloud provider's cron service) would be the better tool for the job.

There's also currently no amount field synced for Payment Terms requests (unlike Credit Limit's shortfall or Margin's gap), so the payment-term flag is judged on type and risk tier only, not amount — if that's ever needed, it means adding a new field to what Metabase sends back and to `sync_dashboard.py`'s output schema.
