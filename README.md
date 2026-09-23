# Approval Matrix — Automated Dashboard

**Live dashboard:** [https://snehaagrawal21.github.io/approval-dashboard/Approval_Matrix_Dashboard.html](https://snehaagrawal21.github.io/approval-dashboard/Approval_Matrix_Dashboard.html)

*Updates itself automatically every day at 10:00 AM IST. No one has to touch it.*

---

## What this is

This is a dashboard built on top of an approval-workflow dataset — thousands of requests across six categories (Credit Limit, Margin, Overdue Checks, Payment Terms, Interest Payments, Supplier POs) and hundreds of organisations — that refreshes itself with zero human involvement.

It automatically finds and flags things like:
- Approvals that went through despite a real shortfall or unpaid dues
- Requests marked "Approved" where nobody on record actually approved them
- The same request failing and being recreated over and over — a sign something's stuck, not just slow
- Auto-approvals that shouldn't have happened under the system's own rules
- Organisations where the same kind of problem shows up across several different categories — a real pattern, not a one-off

Every number and flag on the dashboard is clickable, and drills straight down to the exact requests behind it — who asked for it, who was supposed to approve it, who actually did.

---

## The flow, in one picture

```
   Metabase                sync_dashboard.py                Approval_Matrix_Dashboard.html
 (where the raw   ──────▶   (a script that does     ──────▶   (the live dashboard,
  data lives)                the work automatically)          published as a website)
                                     ▲
                                     │
                         sync-dashboard.yml
                        (tells it when to run)
```

Once a day, on its own: pull fresh data → recheck every rule → update the live page. No exports, no copy-pasting, no remembering to refresh it.

---

## What each file does, and how it actually works

### `Approval_Matrix_Dashboard.html`
This one file *is* the whole dashboard — the filters, the headline numbers, the flagged-issue cards, the category breakdown, the organisation ranking, the full request list (each row traceable back to its Enquiry ID and Approval Request ID), all of it, built right in. Near the bottom of the file sits a block holding every request's data. That block is the *only* part that changes day to day — the look, the flag rules, the click behavior never change on their own.

### `sync_dashboard.py`
A script — a list of instructions a computer follows — written in Python. Each time it runs, it does four things:
1. Logs into Metabase with a stored key and asks for every row of the report
2. Rechecks every request against the same rules that define each flag (shortfall? unsigned approval? request failed and resubmitted 5+ times?) — recalculated fresh every time, never reused from the day before
3. Packages the results the way the dashboard expects
4. Opens the dashboard file and swaps in the new data block, leaving everything else untouched

### `sync-dashboard.yml`
A short instruction file that tells GitHub: *"every day at 4:30 AM UTC (10:00 AM IST), start a computer, install what the script needs, run it, and save what it produces."* It also lets you trigger the same thing manually anytime, which is how you'd test it before trusting it to run alone.

---

## Exactly what happens, every single day

1. **10:00 AM IST.** GitHub's own servers — not anyone's laptop — wake up and start the job.
2. A brand-new, temporary computer is created in the cloud, just for this one run. Python and two small tools get installed on it.
3. The script runs. Two secret values (the Metabase key, and the ID of the specific report to pull) are handed to it securely at that exact moment — never written into any file anyone can see.
4. It asks Metabase for the freshest data available.
5. It rechecks every flag against that fresh data, from scratch.
6. It opens the dashboard file, swaps in the new data, and updates the "snapshot as of" date at the top.
7. The updated file is saved back into the project, replacing yesterday's version.
8. The hosting service notices the file changed and republishes it automatically — no extra step needed.
9. The temporary computer from step 2 is thrown away. It existed for about 20–30 seconds, did its job, and is gone.

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
