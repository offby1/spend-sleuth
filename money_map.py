"""Money Map — turn a bank statement (PDF or CSV) into a map of where the money went.

Usage:
    python money_map.py sample-statement.pdf
    python money_map.py sample-statement.csv

The file type is detected automatically from the file's content (PDFs start
with the %PDF magic bytes), so any extension works. Classifies every
transaction with local keyword rules, detects recurring charges (flagging the
ones that look forgotten), and writes report.md + report.html. Everything runs
locally — your statement never leaves the machine.
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime

try:
    from pypdf import PdfReader
except ImportError:
    sys.exit("money_map needs pypdf to read PDFs:  python3 -m pip install pypdf")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Transaction:
    date: datetime
    description: str
    amount: float          # negative = spending, positive = income
    category: str = "Uncategorized"

    @property
    def month(self) -> str:
        return self.date.strftime("%Y-%m")


# ---------------------------------------------------------------------------
# Step 1: parse the PDF
# ---------------------------------------------------------------------------

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
MONEY_RE = re.compile(r"^-?\$?[\d,]+\.\d{2}$")
# for statements whose rows survive extraction as a single line
ONE_LINE_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?\$?[\d,]+\.\d{2})(?:\s+(-?\$?[\d,]+\.\d{2}))?$"
)

# Chase-style statements: MM/DD dates (year comes from the statement period),
# "- 73.46" for withdrawals, and a running balance at the end of each row.
SHORT_DATE_LINE_RE = re.compile(r"^(\d{2})/(\d{2})\s+(.+)$")
MONEY_TOKEN_RE = re.compile(r"-\s?[\d,]+\.\d{2}|[\d,]+\.\d{2}")
PERIOD_RE = re.compile(
    r"([A-Z][a-z]+)\s+\d{1,2},\s+(\d{4})\s+through\s+([A-Z][a-z]+)\s+\d{1,2},\s+(\d{4})"
)
BEGIN_BAL_RE = re.compile(r"Beginning Balance\s+\$?(-?[\d,]+\.\d{2})")
MONTH_NUM = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}

SKIP_DESCRIPTIONS = {"OPENING BALANCE", "CLOSING BALANCE", "BEGINNING BALANCE", "ENDING BALANCE"}


def parse_money(s: str) -> float:
    s = s.strip().replace("$", "").replace(",", "")
    if s.startswith("(") and s.endswith(")"):   # accounting style: (45.00) = -45.00
        s = "-" + s[1:-1]
    return float(s)


def load(path: str) -> list[Transaction]:
    """Detect the file type from its content and parse accordingly."""
    with open(path, "rb") as f:
        head = f.read(5)
    if head.startswith(b"%PDF"):
        return load_pdf(path)
    return load_csv(path)


def load_pdf(pdf_path: str) -> list[Transaction]:
    """Extract transactions from a bank statement PDF.

    Handles both layouts pypdf produces: whole rows on one line, or each cell
    (date / description / amount / balance) on its own line. When a row carries
    two money values, the first is the amount and the second the running
    balance. Adjust here if your bank's statement reads differently — e.g. if
    spending is printed as positive, flip the sign.
    """
    reader = PdfReader(pdf_path)
    lines: list[str] = []
    for page in reader.pages:
        lines.extend((page.extract_text() or "").splitlines())
    lines = [ln.strip() for ln in lines if ln.strip()]

    txns: list[Transaction] = []

    # Pass 1: rows that survived extraction as single lines
    consumed = set()
    for i, ln in enumerate(lines):
        m = ONE_LINE_RE.match(ln)
        if m and not DATE_RE.match(ln):
            date_s, desc, amt_s, _bal = m.groups()
            if desc.upper() in SKIP_DESCRIPTIONS:
                consumed.add(i)
                continue
            txns.append(Transaction(datetime.strptime(date_s, "%m/%d/%Y"), desc, parse_money(amt_s)))
            consumed.add(i)

    # Pass 2: state machine over cell-per-line layout
    i = 0
    while i < len(lines):
        if i in consumed or not DATE_RE.match(lines[i]):
            i += 1
            continue
        date = datetime.strptime(lines[i], "%m/%d/%Y")
        i += 1
        # description = following non-money lines
        desc_parts = []
        while i < len(lines) and not MONEY_RE.match(lines[i]) and not DATE_RE.match(lines[i]):
            desc_parts.append(lines[i])
            i += 1
        # money values: amount, then optional running balance
        money = []
        while i < len(lines) and MONEY_RE.match(lines[i]) and len(money) < 2:
            money.append(parse_money(lines[i]))
            i += 1
        desc = " ".join(desc_parts).strip()
        if not desc or desc.upper() in SKIP_DESCRIPTIONS or not money:
            continue
        txns.append(Transaction(date, desc, money[0]))

    # Pass 3 (Chase-style): MM/DD dates, running balance at the end of each row.
    # Deposit rows can lose their amount column during extraction, so when we
    # know the previous balance, the amount is derived from the balance change.
    if not txns:
        full_text = "\n".join(lines)
        period = PERIOD_RE.search(full_text)
        years_by_month: dict[int, int] = {}
        if period:
            m1, y1, m2, y2 = period.groups()
            start_m, end_m = MONTH_NUM[m1], MONTH_NUM[m2]
            start_y, end_y = int(y1), int(y2)
            mo, yr = start_m, start_y
            while True:
                years_by_month[mo] = yr
                if (mo, yr) == (end_m, end_y):
                    break
                mo += 1
                if mo > 12:
                    mo, yr = 1, yr + 1
        bal_m = BEGIN_BAL_RE.search(full_text)
        prev_bal = parse_money(bal_m.group(1)) if bal_m else None

        for ln in lines:
            m = SHORT_DATE_LINE_RE.match(ln)
            if not m:
                continue
            month, day, rest = int(m.group(1)), int(m.group(2)), m.group(3)
            if not (1 <= month <= 12 and 1 <= day <= 31):
                continue
            tokens = MONEY_TOKEN_RE.findall(rest)
            if not tokens:
                continue
            # description = the row minus its trailing money columns
            desc = rest
            while True:
                m2 = re.search(r"(?:-\s?)?[\d,]+\.\d{2}\s*$", desc)
                if not m2:
                    break
                desc = desc[: m2.start()].rstrip()
            if not desc:
                continue

            values = [parse_money(t.replace(" ", "")) for t in tokens]
            negatives = [v for v in values if v < 0]
            if negatives:                       # printed withdrawal amount
                amount = negatives[0]
            elif len(values) >= 2:              # amount column + balance column
                amount = values[0]
            elif prev_bal is not None:          # only the balance survived
                amount = round(values[-1] - prev_bal, 2)
            else:                               # no balance to diff against
                amount = values[0]
            if prev_bal is not None:
                prev_bal = values[-1]           # last column is the new balance

            year = years_by_month.get(month, datetime.now().year)
            txns.append(Transaction(datetime(year, month, day), desc, amount))

    txns.sort(key=lambda t: t.date)
    return txns


DATE_FORMATS = ["%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y",
                "%d-%b-%Y", "%b %d, %Y", "%B %d, %Y"]


def parse_date(s: str) -> datetime | None:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def load_csv(csv_path: str) -> list[Transaction]:
    """Parse a bank CSV export. Handles the common shapes: a header row with
    Date / Description / Amount columns (names matched loosely), separate
    Debit / Credit columns, or headerless date,description,amount rows.
    Spending is expected as negative; flip here if your bank exports positives.
    """
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [r for r in csv.reader(f, dialect) if any(c.strip() for c in r)]
    if not rows:
        return []

    def find_col(header, *keywords):
        for i, cell in enumerate(header):
            c = cell.strip().lower()
            if any(k in c for k in keywords):
                return i
        return None

    header = [c.strip().lower() for c in rows[0]]
    date_i = find_col(header, "date")
    desc_i = find_col(header, "description", "details", "payee", "memo", "merchant", "narrative")
    amt_i = find_col(header, "amount")
    debit_i = find_col(header, "debit", "withdrawal")
    credit_i = find_col(header, "credit", "deposit")

    if date_i is not None and desc_i is not None:
        data_rows = rows[1:]
    else:                                   # headerless: date, description, amount
        date_i, desc_i, amt_i, debit_i, credit_i = 0, 1, 2, None, None
        data_rows = rows

    txns: list[Transaction] = []
    for row in data_rows:
        if len(row) <= max(date_i, desc_i):
            continue
        date = parse_date(row[date_i])
        desc = row[desc_i].strip()
        if date is None or not desc or desc.upper() in SKIP_DESCRIPTIONS:
            continue
        try:
            if amt_i is not None and amt_i < len(row) and row[amt_i].strip():
                amount = parse_money(row[amt_i])
            else:                           # separate debit/credit columns
                debit = parse_money(row[debit_i]) if debit_i is not None and row[debit_i].strip() else 0.0
                credit = parse_money(row[credit_i]) if credit_i is not None and row[credit_i].strip() else 0.0
                amount = credit - abs(debit)
        except (ValueError, IndexError):
            continue
        txns.append(Transaction(date, desc, amount))

    txns.sort(key=lambda t: t.date)
    return txns


# ---------------------------------------------------------------------------
# Step 2: categorize (local keyword rules)
# ---------------------------------------------------------------------------

# keyword (matched case-insensitively inside the description) -> category.
# This table is where the tuning happens: add your own bank's merchants.
# ORDER MATTERS: the first matching keyword wins, so specific keywords
# ("UBER EATS", "UBER ONE") must come before generic ones ("UBER").
RULES = {
    # income and transfers
    "PAYROLL": "Income",
    "DIRECT DEPOSIT": "Income",
    "ZELLE PAYMENT FROM": "Zelle Received",
    "ZELLE PAYMENT TO": "Zelle Sent",
    "PAYMENT - THANK YOU": "Card Payment",     # paying the credit card bill
    "MOBILE PAYMENT": "Card Payment",
    "AMERICAN EXPRESS ACH": "Card Payment",
    "EPAY": "Card Payment",
    "AUTOPAY": "Card Payment",
    # housing & utilities
    "RENT": "Housing",
    "PROPERTY MGMT": "Housing",
    "PG&E": "Utilities",
    "COMCAST": "Utilities",
    "XFINITY": "Utilities",
    "VERIZON": "Utilities",
    "T-MOBILE": "Utilities",
    "AT&T": "Utilities",
    # groceries
    "WHOLE FOODS": "Groceries",
    "TRADER JOE": "Groceries",
    "SAFEWAY": "Groceries",
    "KROGER": "Groceries",
    "COSTCO": "Groceries",
    "PATEL BROTHERS": "Groceries",             # before the "BROTHERS" bar rule
    "INSTACART": "Groceries",
    # coffee & snacks
    "STARBUCKS": "Coffee & snacks",
    "TOUS LES JOUR": "Coffee & snacks",
    "SIREN": "Coffee & snacks",
    "UNITED DAIRY": "Coffee & snacks",
    "CANTEEN": "Coffee & snacks",
    # takeout, delivery, restaurants
    "DOORDASH": "Takeout & delivery",
    "UBER EATS": "Takeout & delivery",
    "GRUBHUB": "Takeout & delivery",
    "CHIPOTLE": "Takeout & delivery",
    "MCDONALD": "Takeout & delivery",
    "TST*": "Takeout & delivery",              # Toast POS = restaurants
    "KAWA": "Takeout & delivery",
    "BEELINE": "Takeout & delivery",
    "BROTHERS": "Takeout & delivery",
    "JAGDEEP": "Takeout & delivery",
    "HYDERABAD": "Takeout & delivery",
    "NAMASTE": "Takeout & delivery",
    "RESTAURANT": "Takeout & delivery",        # generic catch-all
    "TSAOCHA": "Coffee & snacks",              # boba
    # subscriptions (before generic UBER)
    "UBER ONE": "Subscriptions",
    "NETFLIX": "Subscriptions",
    "SPOTIFY": "Subscriptions",
    "ADOBE": "Subscriptions",
    "ICLOUD": "Subscriptions",
    "APPLE.COM/BIL": "Subscriptions",
    "WHOOP": "Subscriptions",
    "FITNESS": "Subscriptions",
    "GYM": "Subscriptions",
    # transport & travel — Uber rides count as Travel per user preference
    "UBER TRIP": "Travel",
    "UBER": "Travel",
    "LYFT": "Transport",
    "SHELL OIL": "Transport",
    "CHEVRON": "Transport",
    "LOVE'S": "Transport",                     # gas stations
    "VENTRA": "Transport",                     # Chicago transit
    # travel
    "AIRBNB": "Travel",
    "ENTERPRISE": "Travel",                    # car rental
    "EAGLEWOOD": "Travel",
    # entertainment
    "AMC ": "Entertainment",
    "IMAX": "Entertainment",
    "SHEDD": "Entertainment",
    "SHORELINE MAR": "Entertainment",
    "ALLDORSS": "Entertainment",
    # health
    "CAMPUS REC": "Health",
    "CVS": "Health",
    "WALGREENS": "Health",
    # shopping
    "AMAZON": "Shopping",
    "TARGET": "Shopping",
    "WALMART": "Shopping",
    "ULTA": "Shopping",
    "ACE HDWE": "Shopping",
    "GROUPON": "Shopping",
}

# money moved between your own accounts — excluded from income AND spending
TRANSFER_CATEGORIES = {"Card Payment"}
INCOME_CATEGORIES = {"Income", "Zelle Received"}


def maybe_flip_signs(txns: list[Transaction]) -> bool:
    """Credit-card exports (Amex, some others) print charges as POSITIVE and
    payments as negative — the mirror of a checking account. If the large
    majority of rows are positive, assume that convention and flip everything
    so that spending is negative throughout the pipeline."""
    if len(txns) < 5:
        return False
    positive = sum(1 for t in txns if t.amount > 0)
    if positive / len(txns) >= 0.7:
        for t in txns:
            t.amount = -t.amount
        return True
    return False


def categorize(txns: list[Transaction]) -> list[Transaction]:
    for t in txns:
        desc = t.description.upper()
        for keyword, category in RULES.items():
            if keyword in desc:
                t.category = category
                break
        else:
            t.category = "Income" if t.amount > 0 else "Uncategorized"
    return txns


# ---------------------------------------------------------------------------
# Step 3: recurring detection
# ---------------------------------------------------------------------------

def normalize_merchant(description: str) -> str:
    """STARBUCKS #5567 and STARBUCKS #212 are one merchant."""
    d = description.upper()
    d = re.sub(r"^APLPAY\s+", "", d)       # Apple Pay prefix on card statements
    # payment-processor prefixes: the real merchant is AFTER the star
    d = re.sub(r"^(IC|TST|CTLP|SQ|PP|PAYPAL|PY)\s?\*\s*", "", d)
    d = re.sub(r"\*.*$", "", d)            # DOORDASH*RESTAURANT -> DOORDASH
    d = re.sub(r"#\S*", "", d)             # store numbers: STARBUCKS #5567 -> STARBUCKS
    d = re.sub(r"WEB ID:?.*$", "", d)      # trailing ACH "Web ID: 123..." junk
    d = re.sub(r"\b\w*\d{4,}\w*\b", "", d) # long alphanumeric reference codes
    d = re.sub(r"\b\d{3,}\b", "", d)       # long trailing reference numbers
    d = re.sub(r"\s+", " ", d).strip()
    return d


@dataclass
class Recurring:
    merchant: str
    months: list[str]
    monthly_avg: float      # average spend per month (positive number)
    fixed_price: bool       # same amount every charge
    category: str
    likely_forgotten: bool


def detect_recurring(txns: list[Transaction], min_months: int = 2) -> list[Recurring]:
    """Group spending by normalized merchant; anything hitting 2+ distinct
    months is recurring. A fixed-price monthly charge of $20+ in a
    subscription-ish category gets the "likely forgotten" flag — that's the
    $39.99 gym you stopped going to and the Adobe plan on autopilot."""
    by_merchant: dict[str, list[Transaction]] = defaultdict(list)
    for t in txns:
        if t.amount < 0:
            by_merchant[normalize_merchant(t.description)].append(t)

    recurring = []
    for merchant, ts in by_merchant.items():
        months = sorted({t.month for t in ts})
        if len(months) < min_months:
            continue
        amounts = [abs(t.amount) for t in ts]
        fixed = max(amounts) - min(amounts) <= 0.01 * max(amounts)
        monthly_avg = sum(amounts) / len(months)
        category = ts[0].category
        forgotten = (
            fixed
            and len(ts) == len(months)             # exactly one charge per month
            and category == "Subscriptions"
            and monthly_avg >= 20
        )
        recurring.append(Recurring(merchant, months, monthly_avg, fixed, category, forgotten))

    recurring.sort(key=lambda r: -r.monthly_avg)
    return recurring


# ---------------------------------------------------------------------------
# Step 4: summarize
# ---------------------------------------------------------------------------

def summarize(txns: list[Transaction]):
    """Income / spending / per-category totals. Card payments are transfers
    between your own accounts, so they're excluded from both sides (their
    total is returned separately for the report). Refunds — positive amounts
    in a spending category — net against that category."""
    income = 0.0
    transfers = 0.0
    by_category: dict[str, float] = defaultdict(float)
    for t in txns:
        if t.category in TRANSFER_CATEGORIES:
            transfers += abs(t.amount)
        elif t.amount > 0 and t.category in INCOME_CATEGORIES:
            income += t.amount
        else:
            by_category[t.category] += -t.amount
    # a category netting negative means refunds exceeded purchases in this
    # window — count the surplus as money in rather than dropping it
    income += sum(-v for v in by_category.values() if v < 0)
    categories = sorted(
        ((c, v) for c, v in by_category.items() if v > 0.005),
        key=lambda kv: -kv[1])
    spent = sum(v for _, v in categories)
    return income, spent, categories, transfers


def month_label(month: str) -> str:
    return datetime.strptime(month, "%Y-%m").strftime("%b %Y")


def summarize_monthly(txns: list[Transaction]) -> dict[str, tuple]:
    """summarize() per calendar month, in chronological order."""
    return {m: summarize([t for t in txns if t.month == m])
            for m in sorted({t.month for t in txns})}


def month_over_month(monthly: dict[str, tuple]) -> list[tuple[str, str, list[str]]]:
    """For each consecutive month pair, the notable per-category changes,
    biggest dollar swing first — 'Takeout & delivery roughly doubled'."""
    notes = []
    months = list(monthly)
    for prev_m, cur_m in zip(months, months[1:]):
        prev = dict(monthly[prev_m][2])
        cur = dict(monthly[cur_m][2])
        changes = []
        for cat in set(prev) | set(cur):
            p, c = prev.get(cat, 0.0), cur.get(cat, 0.0)
            if abs(c - p) < 25:                      # ignore small swings
                continue
            if p == 0:
                txt = f"{cat}: new this month at ${c:,.2f}"
            elif c == 0:
                txt = f"{cat}: dropped to $0 (was ${p:,.2f})"
            else:
                r = c / p
                if r >= 2.5:
                    word = f"{r:.1f}× last month"
                elif r >= 1.8:
                    word = "roughly doubled"
                elif r >= 1.25:
                    word = f"up {r - 1:.0%}"
                elif r <= 0.55:
                    word = "roughly halved" if r > 0.4 else f"down {1 - r:.0%}"
                elif r <= 0.8:
                    word = f"down {1 - r:.0%}"
                else:
                    continue                          # under ±25% — not notable
                txt = f"{cat} {word} — ${p:,.2f} → ${c:,.2f}"
            changes.append((abs(c - p), txt))
        changes.sort(key=lambda x: -x[0])
        notes.append((month_label(prev_m), month_label(cur_m),
                      [t for _, t in changes[:6]]))
    return notes


# ---------------------------------------------------------------------------
# Step 5: advice — local heuristics
# ---------------------------------------------------------------------------

def local_advice(income, spent, categories, recurring, n_months) -> list[str]:
    if not categories or spent <= 0:
        return ["No spending found to advise on."]
    advice = []
    forgotten = [r for r in recurring if r.likely_forgotten]
    if forgotten:
        total = sum(r.monthly_avg for r in forgotten)
        names = ", ".join(r.merchant.title() for r in forgotten)
        advice.append(
            f"Cancel or downgrade the flagged subscriptions ({names}) — "
            f"that's ${total:,.2f}/month, ${total * 12:,.2f}/year on autopilot."
        )
    discretionary = [(c, v) for c, v in categories
                     if c in {"Takeout & delivery", "Coffee & snacks",
                              "Shopping", "Entertainment"}]
    if discretionary:
        cat, val = max(discretionary, key=lambda kv: kv[1])
        advice.append(
            f"{cat} is your biggest discretionary category at ${val / n_months:,.2f}/month; "
            f"halving it saves ${val / n_months / 2:,.2f}/month."
        )
    top_cat, top_val = categories[0]
    advice.append(
        f"{top_cat} is {top_val / spent:.0%} of all spending "
        f"(${top_val / n_months:,.2f}/month) — the single biggest lever if it's negotiable."
    )
    return advice[:3]


# ---------------------------------------------------------------------------
# Step 6: reports
# ---------------------------------------------------------------------------

def bar(value, max_value, width=30) -> str:
    filled = round(width * value / max_value) if max_value else 0
    return "█" * filled + "░" * (width - filled)


def monthly_table_rows(monthly):
    """(header_cells, rows) for the category-by-month table. Categories are
    ordered by overall size; Income / Spent / Net summary rows come first."""
    months = list(monthly)
    cat_totals: dict[str, float] = defaultdict(float)
    for m in months:
        for c, v in monthly[m][2]:
            cat_totals[c] += v
    cat_order = [c for c, _ in sorted(cat_totals.items(), key=lambda kv: -kv[1])]

    header = ["Category"] + [month_label(m) for m in months]
    rows = []
    for label, idx in (("Income", 0), ("Spent", 1)):
        rows.append([f"**{label}**"] + [f"${monthly[m][idx]:,.2f}" for m in months])
    rows.append(["**Net**"] + [
        f"{'+' if monthly[m][0] >= monthly[m][1] else '-'}"
        f"${abs(monthly[m][0] - monthly[m][1]):,.2f}" for m in months])
    for c in cat_order:
        per_month = [dict(monthly[m][2]).get(c) for m in months]
        rows.append([c] + [f"${v:,.2f}" if v is not None else "—" for v in per_month])
    return header, rows


def write_markdown(path, source, income, spent, categories, recurring, advice,
                   n_months, transfers=0.0, monthly=None, mom=None):
    max_val = categories[0][1] if categories else 1
    lines = [
        "# Money Map",
        "",
        f"Source: `{source}` — {n_months} month(s) of activity",
        "",
        f"**Income:** ${income:,.2f} · **Spent:** ${spent:,.2f} · "
        f"**Net:** {'+' if income >= spent else '-'}${abs(income - spent):,.2f}",
        "",
    ]
    if transfers:
        lines += [f"*${transfers:,.2f} in card payments excluded — transfers "
                  f"between your own accounts, not income or spending.*", ""]
    lines += [
        "## Where it went",
        "",
        "| Category | Total | Per month | |",
        "|---|---:|---:|---|",
    ]
    for cat, val in categories:
        lines.append(f"| {cat} | ${val:,.2f} | ${val / n_months:,.2f} | `{bar(val, max_val)}` |")

    if monthly and len(monthly) > 1:
        header, rows = monthly_table_rows(monthly)
        lines += ["", "## Month by month", "",
                  "| " + " | ".join(header) + " |",
                  "|---|" + "---:|" * (len(header) - 1)]
        lines += ["| " + " | ".join(r) + " |" for r in rows]

    if mom:
        lines += ["", "## Month-over-month changes", ""]
        for prev_l, cur_l, items in mom:
            lines.append(f"**{cur_l} vs {prev_l}:**")
            lines += [f"- {it}" for it in items] or ["- no notable changes"]
            lines.append("")

    lines += ["", "## Recurring charges", ""]
    for r in recurring:
        flag = " ⚠️ **likely forgotten**" if r.likely_forgotten else ""
        price = "fixed" if r.fixed_price else "varies"
        lines.append(
            f"- **{r.merchant.title()}** — ${r.monthly_avg:,.2f}/month "
            f"({price}, seen in {len(r.months)} months, {r.category}){flag}"
        )
    lines += ["", "## Top 3 changes", ""]
    lines += [f"{i}. {a}" for i, a in enumerate(advice, 1)]
    lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines))


def write_html(path, source, income, spent, categories, recurring, advice,
               n_months, transfers=0.0, monthly=None, mom=None):
    max_val = categories[0][1] if categories else 1

    monthly_html = ""
    if monthly and len(monthly) > 1:
        header, rows = monthly_table_rows(monthly)
        head = "".join(f"<th>{html.escape(h)}</th>" for h in header)
        body = ""
        for r in rows:
            label = r[0].strip("*")
            cls = ' class="sumrow"' if r[0].startswith("**") else ""
            cells = "".join(f"<td>{html.escape(v)}</td>" for v in r[1:])
            body += f"<tr{cls}><td>{html.escape(label)}</td>{cells}</tr>"
        monthly_html = (f'<div class="card"><h2>Month by month</h2>'
                        f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
                        f'<tbody>{body}</tbody></table></div></div>')

    mom_html = ""
    if mom:
        blocks = ""
        for prev_l, cur_l, items in mom:
            lis = "".join(f"<li>{html.escape(it)}</li>" for it in items) \
                  or "<li>no notable changes</li>"
            blocks += (f'<h3>{html.escape(cur_l)} vs {html.escape(prev_l)}</h3>'
                       f'<ul>{lis}</ul>')
        mom_html = f'<div class="card"><h2>Month-over-month changes</h2>{blocks}</div>'
    transfer_note = (
        f'<p class="sub" style="flex-basis:100%">${transfers:,.2f} in card payments '
        f'excluded — transfers between your own accounts, not income or spending.</p>'
        if transfers else "")
    cat_rows = "\n".join(
        f'<div class="row"><div class="label">{html.escape(cat)}</div>'
        f'<div class="track"><div class="bar" style="width:{val / max_val * 100:.1f}%"></div></div>'
        f'<div class="val">${val:,.2f}</div></div>'
        for cat, val in categories
    )
    rec_rows = "\n".join(
        f'<li class="{"flagged" if r.likely_forgotten else ""}">'
        f'<strong>{html.escape(r.merchant.title())}</strong> — ${r.monthly_avg:,.2f}/month '
        f'({"fixed" if r.fixed_price else "varies"}, {len(r.months)} months, {html.escape(r.category)})'
        f'{" <span class=flag>⚠️ likely forgotten</span>" if r.likely_forgotten else ""}</li>'
        for r in recurring
    )
    advice_rows = "\n".join(f"<li>{html.escape(a)}</li>" for a in advice)
    net = income - spent
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Money Map</title>
<style>
  :root {{ --ink:#1a2332; --muted:#67728a; --accent:#2f6fed; --bg:#f7f8fb; --card:#fff; }}
  * {{ box-sizing:border-box; margin:0; }}
  body {{ font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background:var(--bg); color:var(--ink); padding:2rem 1rem; }}
  main {{ max-width:760px; margin:0 auto; display:grid; gap:1.25rem; }}
  .card {{ background:var(--card); border-radius:12px; padding:1.5rem;
           box-shadow:0 1px 3px rgba(20,30,60,.08); }}
  h1 {{ font-size:1.6rem; }} h2 {{ font-size:1.1rem; margin-bottom:1rem; }}
  .sub {{ color:var(--muted); font-size:.9rem; margin-top:.35rem; }}
  .totals {{ display:flex; gap:2rem; flex-wrap:wrap; }}
  .totals .num {{ font-size:1.35rem; font-weight:700; }}
  .totals .neg {{ color:#c0392b; }} .totals .pos {{ color:#1e8e4e; }}
  .row {{ display:grid; grid-template-columns:110px 1fr 90px; gap:.75rem;
          align-items:center; margin-bottom:.55rem; font-size:.9rem; }}
  .track {{ background:#e8ecf4; border-radius:6px; height:18px; overflow:hidden; }}
  .bar {{ background:var(--accent); height:100%; border-radius:6px; }}
  .val {{ text-align:right; font-variant-numeric:tabular-nums; }}
  ul, ol {{ padding-left:1.2rem; }} li {{ margin-bottom:.5rem; font-size:.92rem; }}
  li.flagged {{ background:#fff7e6; border-radius:8px; padding:.5rem .75rem; list-style:none;
                margin-left:-1.2rem; border:1px solid #f4d896; }}
  .flag {{ color:#a86500; font-weight:600; }}
  h3 {{ font-size:.95rem; margin:.9rem 0 .4rem; }}
  .scroll {{ overflow-x:auto; }}
  table {{ border-collapse:collapse; width:100%; font-size:.88rem; }}
  th, td {{ padding:.4rem .7rem; text-align:right; white-space:nowrap; }}
  th:first-child, td:first-child {{ text-align:left; }}
  thead th {{ border-bottom:2px solid #d7dcea; }}
  tbody td {{ border-bottom:1px solid #edf0f7; font-variant-numeric:tabular-nums; }}
  tr.sumrow td {{ font-weight:700; background:#f3f5fa; }}
</style>
</head>
<body>
<main>
  <div class="card">
    <h1>Money Map</h1>
    <p class="sub">Source: {html.escape(source)} · {n_months} month(s) of activity</p>
  </div>
  <div class="card totals">
    <div><div class="sub">Income</div><div class="num pos">${income:,.2f}</div></div>
    <div><div class="sub">Spent</div><div class="num neg">${spent:,.2f}</div></div>
    <div><div class="sub">Net</div><div class="num {'pos' if net >= 0 else 'neg'}">{'+' if net >= 0 else '-'}${abs(net):,.2f}</div></div>
    {transfer_note}
  </div>
  <div class="card"><h2>Where it went</h2>{cat_rows}</div>
  {monthly_html}
  {mom_html}
  <div class="card"><h2>Recurring charges</h2><ul>{rec_rows}</ul></div>
  <div class="card"><h2>Top 3 changes</h2><ol>{advice_rows}</ol></div>
</main>
</body>
</html>"""
    with open(path, "w") as f:
        f.write(doc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Map where the money in bank statements (PDF or CSV) went.")
    ap.add_argument("statements", nargs="+",
                    help="one or more statement PDFs/CSVs (type auto-detected from content)")
    ap.add_argument("--flip", action="store_true",
                    help="force-flip signs (statement prints spending as positive)")
    ap.add_argument("--no-flip", action="store_true",
                    help="disable the automatic credit-card sign detection")
    args = ap.parse_args()

    # Load each file separately: sign detection is per file (a credit-card
    # export and a checking statement have opposite conventions).
    per_file: list[Counter] = []
    for path in args.statements:
        txns = load(path)
        if not txns:
            print(f"warning: no transactions found in {path} — skipping "
                  "(adjust load_pdf()/load_csv() if this is unexpected)")
            continue
        if args.flip:
            for t in txns:
                t.amount = -t.amount
            print(f"{path}: signs flipped (--flip).")
        elif not args.no_flip and maybe_flip_signs(txns):
            print(f"{path}: credit-card sign convention detected (charges "
                  "positive) — signs flipped. Use --no-flip to override.")
        per_file.append(Counter((t.date, t.description, t.amount) for t in txns))
    if not per_file:
        sys.exit("No transactions found in any file.")

    # Merge with overlap-dedup: a row appearing in several files (overlapping
    # statement periods) is kept at the highest count seen in any ONE file, so
    # genuine same-day duplicates within a file survive.
    merged: Counter = Counter()
    for c in per_file:
        for key, n in c.items():
            merged[key] = max(merged[key], n)
    dropped = sum(c.total() for c in per_file) - merged.total()
    if dropped:
        print(f"{dropped} duplicate transaction(s) across overlapping statements ignored.")

    txns = [Transaction(d, desc, amt) for (d, desc, amt), n in merged.items() for _ in range(n)]
    txns.sort(key=lambda t: t.date)
    txns = categorize(txns)

    n_months = len({t.month for t in txns})
    income, spent, categories, transfers = summarize(txns)
    monthly = summarize_monthly(txns)
    mom = month_over_month(monthly)
    recurring = detect_recurring(txns)

    advice = local_advice(income, spent, categories, recurring, n_months)

    source = ", ".join(args.statements)
    write_markdown("report.md", source, income, spent, categories,
                   recurring, advice, n_months, transfers, monthly, mom)
    write_html("report.html", source, income, spent, categories,
               recurring, advice, n_months, transfers, monthly, mom)

    flagged = sum(r.likely_forgotten for r in recurring)
    print(f"{len(txns)} transactions from {len(per_file)} file(s) across {n_months} months")
    print(f"Income ${income:,.2f} | Spent ${spent:,.2f} | Net ${income - spent:+,.2f}")
    print(f"{len(recurring)} recurring merchants, {flagged} flagged as likely forgotten")
    print("Wrote report.md and report.html")


if __name__ == "__main__":
    main()
