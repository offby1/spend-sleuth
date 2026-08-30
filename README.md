# 🕵️ Spend Sleuth

**Point it at your bank statements. Find out where the money actually went — and which subscriptions you forgot you were paying for.**

Drop in your statements (PDF *or* CSV, any number of them), run one command, and get a
clean report: spending by category, a month-by-month breakdown, month-over-month
changes like *"Takeout & delivery roughly doubled"*, and the recurring charges that
look forgotten.

**100% local. No API keys, no accounts, no network calls.** Your financial data never
leaves your machine — not one byte.

```bash
python3 money_map.py june.pdf july.pdf amex-activity.csv
```

```
55 transactions from 3 file(s) across 3 months
Income $4,200.00 | Spent $1,566.85 | Net $+2,633.15
18 recurring merchants, 2 flagged as likely forgotten
Wrote report.md and report.html
```

---

## Why

Every budgeting app wants you to hand over your bank login. This one doesn't. It reads
the statement files you already have, does the work locally in plain Python, and writes
you a report you can actually read.

## What you get

- **Where it went** — every transaction categorized, sorted by total, with bar charts
- **Month by month** — a table of every category across every month you feed it
- **Month-over-month changes** — *"Shopping roughly doubled — $79.83 → $148.75"*
- **⚠️ Likely forgotten subscriptions** — fixed-price monthly charges that smell abandoned (the $39.99 gym you stopped going to)
- **Top 3 changes** — concrete suggestions with dollar amounts attached
- Output as both `report.md` (read in your terminal) and `report.html` (open in a browser)

## Quickstart

**1. Clone and enter the repo**

```bash
git clone https://github.com/GOkul069/spend-sleuth.git
```

```bash
cd spend-sleuth
```

**2. Install the dependencies** (Python 3.10+)

```bash
python3 -m pip install -r requirements.txt
```

**3. Generate the sample statement** — a fictional 3-month statement, in both PDF and CSV

```bash
python3 make_sample_statement.py
```

**4. Run it**

```bash
python3 money_map.py sample-statement.pdf
```

**5. Open the report**

```bash
open report.html
```

(on Linux use `xdg-open report.html`, on Windows just `report.html`)

You'll see categories with bar charts, month-over-month changes, and two subscriptions
flagged ⚠️ **likely forgotten** — the gym and Adobe.

## Use it on your own statements

Download statements from your bank — PDF or CSV, whatever they give you — and run:

```bash
python3 money_map.py my-statement.pdf
```

Feed it several at once to get a combined report with monthly trends. PDFs and CSVs mix
freely, and the file type is detected from each file's **content**, not its extension:

```bash
python3 money_map.py june.pdf july.pdf august.pdf checking-export.csv
```

Overlapping statements are deduplicated, and sign conventions are detected per file — so
a credit-card export (charges positive) and a checking statement (spending negative)
combine correctly in one report.

### Options

| Flag | What it does |
|---|---|
| `--flip` | Force-flip signs (your statement prints spending as positive) |
| `--no-flip` | Disable the automatic credit-card sign detection |

## Tuning it to your bank

The one thing you should expect to edit is the `RULES` dictionary in `money_map.py` — a
plain `keyword → category` table:

```python
RULES = {
    "WHOLE FOODS": "Groceries",
    "UBER EATS":   "Takeout & delivery",
    "NETFLIX":     "Subscriptions",
    ...
}
```

Your bank's merchant descriptions differ from anyone else's, so if a lot of spending
lands in **Uncategorized**, add your merchants here. Order matters: the first matching
keyword wins, so put specific keywords above generic ones (`UBER EATS` before `UBER`).

## How it works

```
statements (.pdf / .csv)
   ↓  detect file type from content, parse each file
transactions
   ↓  auto-detect sign convention, merge + dedupe across files
   ↓  categorize with local keyword rules
   ↓  normalize merchants (STARBUCKS #5567 ≡ STARBUCKS #212) → detect recurring
   ↓  summarize overall, per month, and month-over-month
report.md  +  report.html
```

**Statement formats it handles**

- **PDF**: rows extracted as one line, as one cell per line, and Chase-style statements
  (MM/DD dates with a running balance per row). `pypdf` reads digital text only — a
  scanned statement needs OCR first.
- **CSV**: header names matched loosely (`Date` / `Posting Date`, `Description` /
  `Details` / `Payee`, `Amount`, or separate `Debit` / `Credit` columns), headerless
  `date,description,amount` rows, quoted thousands, and accounting-style negatives like
  `(45.00)`.

**Things it gets right that trip up spreadsheets**

- **Card payments are transfers.** Rows like `MOBILE PAYMENT - THANK YOU` move money
  between your own accounts, so they're excluded from both income and spending (the
  excluded total is noted in the report) instead of being double-counted as expenses.
- **Refunds net against their category** rather than inflating your spending.
- **Store numbers are noise.** `STARBUCKS #5567` and `STARBUCKS #212` are one merchant;
  processor prefixes like `IC*` and `TST*` and Apple Pay's `AplPay` are stripped.

## How "likely forgotten" works

`detect_recurring()` groups spending by normalized merchant and treats anything appearing
in 2+ distinct months as recurring. It gets the ⚠️ flag when it's a **fixed-price,
exactly-once-a-month charge of $20+ in a subscription category** — the profile of a
subscription running on autopilot. Groceries show up as recurring too, and that's
correct; the flag is what points at the forgotten ones.

## Privacy

There is no network code in this tool. No API keys, no telemetry, no uploads — parsing,
categorizing, and report generation all happen in local Python.

The included `.gitignore` blocks `*.pdf`, `*.csv`, and the generated `report.*` files, so
you can fork this, tune the rules to your own bank, and push your changes without ever
risking a commit of your actual finances.

## Roadmap

- Detect a subscription's **price increase** over time (Netflix went up — by how much?)
- Budgets: color a category red when it exceeds a target you set
- Real pie/line charts in the HTML report
- Merchant rules in a config file instead of in the source

## License

MIT — see [LICENSE](LICENSE).
