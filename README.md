# Approval Matrix — Automated Dashboard

**Live dashboard:** [https://snehaagrawal21.github.io/approval-dashboard/Approval_Matrix_Dashboard.html](https://snehaagrawal21.github.io/approval-dashboard/Approval_Matrix_Dashboard.html)

*Updates itself automatically every day at 10:00 AM IST. Password-protected. No one has to touch it.*

---

## What this is

A dashboard on top of the approval-workflow dataset — thousands of requests across six categories (Credit Limit, Margin, Overdue, Payment Terms, Interest Payment, Supplier PO) — that refreshes itself with zero human involvement.

It automatically finds and flags things like:
- Approvals that went through despite a real credit shortfall, margin gap, or unpaid dues (whether that slipped through automatically or a reviewer approved it anyway)
- Payment terms that quietly got riskier than what was required — and slipped through, sometimes with no one even reviewing it
- Requests marked "Approved" where nobody on record actually signed off
- The same request failing and being recreated over and over (verified against the database, not just guessed from the text) — a sign something's stuck, not just slow
- Requests that have been sitting unresolved for two weeks or more
- The reverse problem too: requests that had *nothing* wrong with them, yet still didn't sail through automatically — a sign of friction in the auto-approval rule itself, not a real risk

Every number and flag is clickable and drills down to the exact requests behind it. Filter by category, organisation, requester, approver, status, date range, Enquiry ID, or Approval Request ID — any combination at once, plus one-click "last 1 month" / "last 2 months" presets. Every click-through (a KPI card, an alert, a breakdown cell, a bucket) is a step you can undo and redo with the **← Back / Forward →** buttons, not just a hard reset.

The Request Explorer table itself stays out of the way until you actually need it — hidden on first load, and appears the moment you click anything.

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
This one file *is* the whole dashboard — the password gate, filters, KPI cards, the flagged-issue alert cards, the category breakdown, the full request list, all of it, built right in. Near the bottom of the file sits a block holding every request's *raw* data. That block is the only part that changes day to day.

**Every flag and threshold is decided inside this file, in JavaScript, the moment it loads** — not precomputed anywhere upstream. That's deliberate: it means there is exactly one place where the business rules live. If a threshold ever needs to change, it changes here, and only here.

**Every count is based on distinct Enquiry ID, not on individual requests.** One enquiry can generate up to 6 category checks (Credit Limit, Margin, Overdue, Payment Terms, Interest, Supplier PO); if 3 of those are flagged at once, that's 1 enquiry needing attention, not 3. The underlying request-level total is still shown alongside, in small text, wherever the two numbers actually differ.

**Invalid requests are excluded from the whole dashboard, everywhere** — not useful, so they're filtered out at the source rather than shown and ignored.

The current flag scheme, all computed from the raw fields, sorted within each colour by how much it actually matters to the business (real money at risk first, process/efficiency issues last):

| Flag | Condition |
|---|---|
| Zero sign-off | Status Approved, ≥1 approver listed, but none of them actually signed off — the single most alarming case |
| Overdue — Red / Yellow | Approved (auto or manual) despite dues outstanding: **>₹1L = Red, ₹0–1L = Yellow**. Has bucket drill-down by amount |
| Credit Limit — Red / Yellow | Approved (auto or manual) despite a shortfall: **>₹1L = Red, ₹0–1L = Yellow**. Has bucket drill-down by amount |
| Margin — Red / Yellow | Approved (auto or manual) despite the required margin not being met: **>₹1L gap = Red, ₹0–1L = Yellow**. Has bucket drill-down by amount |
| Interest Payment — Red / Yellow | Not recorded as received, approved anyway: **delay >30 days = Red, 10–30 days = Yellow**. Has bucket drill-down by delay |
| Payment Terms downgrade | Type doesn't match, **and** the organisation's actual term is genuinely riskier than what the enquiry required (Advance < LC/BG < POD < Credit) — a same-or-safer substitution is *not* flagged. One merged card (always Red); click through to a bucket picking Auto-Approved vs manually Approved |
| Retry loop | Status Pending, verified against the database as having failed and been recreated 5+ times. Has bucket drill-down by retry count |
| 5 "clean, but not auto-approved" flags | One per category (Credit Limit, Margin, Overdue, Interest, Payment Terms) — the request met every condition for a clean auto-approval, yet still needed a manual decision. Always Red when present; click through to a bucket picking Pending vs Approved |
| Stuck pending 14+ days | Status Pending, sitting unresolved for 14+ days. Has bucket drill-down by age |

Green ("nothing wrong") is never shown as a card — only real problems get one. Yellow cards are collapsed behind "View more" by default; every Red card always shows in full.

**KPI row**, all clickable, all with a "by approval type" bucket breakdown (except Still Waiting, which breaks down by age instead): Total Enquiries, Rejected, Auto-Approved, Approved, Still Waiting, Worth a Closer Look. Each card's "i" icon opens a second popup showing how many enquiries touched 1 of the 6 approval types, how many touched 2, and so on — useful context for why a category breakdown doesn't sum back to the card's own total.

### `sync_dashboard.py`
A script that runs once a day and does exactly one job: keep the data fresh. Each run:
1. Logs into Metabase with a stored key and pulls every row of the report
2. Cleans it up and verifies the retry-loop churn count — this is the one piece of logic that genuinely has to happen here, because it means cross-checking every request's message history against the *entire* dataset to confirm which prior attempts are real (an ID only counts if it's actually found elsewhere in the data with status Invalid — text alone isn't trusted)
3. Packages the result into the compact format the dashboard expects — raw fields only, no flags baked in
4. Opens the dashboard file and swaps in the new data block, leaving everything else — styling, flags, the password gate, click behaviour — completely untouched

### `sync-dashboard.yml`
A short instruction file that tells GitHub: *"every day at 4:30 AM UTC (10:00 AM IST), start a computer, install what the script needs, run it, and save what it produces."* It also lets you trigger the same run manually anytime, which is how you'd test it before trusting it to run alone.

---

## Password protection

The dashboard opens behind a lock screen — nothing renders until the right password is entered. It's entirely self-contained in the HTML file: a SHA-256 hash sits near the top of the `<script>` block, and the visitor's own browser checks their entered password against it locally. `sync_dashboard.py` never touches this, and a daily sync never resets or weakens it.

Once someone enters it correctly, that browser remembers it (via `localStorage`) and won't ask again on that device — convenient, but it also means anyone else using that same browser gets in without re-entering it. It'll ask again if the browser's site data is cleared, in a private/incognito window, or on a different browser or device.

**To change the password:** open any browser's dev console and run
```js
crypto.subtle.digest('SHA-256', new TextEncoder().encode('yourNewPassword'))
  .then(b=>console.log([...new Uint8Array(b)].map(x=>x.toString(16).padStart(2,'0')).join('')))
```
then paste the printed hash over the `LOCK_HASH` value in the HTML file.

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
9. The moment anyone opens the page (and unlocks it), the dashboard's own JavaScript reads that fresh raw data and works out every flag itself, live.
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
| The password hash | Keeps the dashboard's contents private to whoever you've given the password to, without needing GitHub Enterprise or a paid hosting tier |

---

## The result

One link, always current, that anyone with the password can open and immediately understand — what's happening, what needs a second look, and why — without a spreadsheet, a manual refresh, or someone explaining it to them.

**Live dashboard:** [https://snehaagrawal21.github.io/approval-dashboard/Approval_Matrix_Dashboard.html](https://snehaagrawal21.github.io/approval-dashboard/Approval_Matrix_Dashboard.html)

---

## Honest limitations

- **Scheduler precision.** This runs on GitHub's free scheduler, which can occasionally start a few minutes later than the set time during busy periods — perfectly fine for a once-a-day refresh, not something to rely on for exact-second timing.
- **No amount field for Payment Terms.** Unlike Credit Limit's shortfall or Margin's gap, there's currently no amount synced for Payment Terms requests, so that flag is judged on type and risk tier only — adding amount would mean a new field in both Metabase and `sync_dashboard.py`'s output schema.
- **Password gate is a deterrent, not real security.** It stops someone who just clicks the link, but the underlying data is still embedded in the HTML file itself — anyone who views page source or downloads the file can see it regardless of the lock screen. For genuine access control (restricting who can see it at all, not just who can click past a prompt), that requires GitHub Enterprise Cloud or hosting elsewhere with real authentication.
- **A rare bucket-count quirk, already flagged where it happens.** A bucket answers "how many enquiries have at least one matching row in this range" — since one enquiry can have rows in two different ranges at once (e.g. two categories stuck pending at different ages), the ranges can occasionally add up to more than the modal's own total. Wherever this happens, the modal says so directly rather than leaving the numbers unexplained.
