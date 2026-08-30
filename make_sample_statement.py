"""Generate sample-statement.pdf — a fake 3-month bank statement.

Run once to (re)create the sample PDF that money_map.py parses:

    python make_sample_statement.py

The data is entirely fictional. It deliberately includes:
  - a paycheck deposit each month (income)
  - messy merchant names with store numbers (STARBUCKS #5567 vs #212)
  - recurring subscriptions, two of which look "forgotten"
    (IRONWORKS FITNESS gym, ADOBE CREATIVE CLOUD)
"""

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# (date, description, amount)  — negative = spending, positive = income
TRANSACTIONS = [
    # ---------------- June 2026 ----------------
    ("06/01/2026", "PAYROLL DEPOSIT ACME CORP", 4200.00),
    ("06/01/2026", "APEX PROPERTY MGMT RENT", -1650.00),
    ("06/02/2026", "NETFLIX.COM", -15.49),
    ("06/03/2026", "IRONWORKS FITNESS #17", -39.99),
    ("06/04/2026", "WHOLE FOODS MKT #10233", -112.47),
    ("06/05/2026", "STARBUCKS #5567", -6.45),
    ("06/07/2026", "ADOBE CREATIVE CLOUD", -54.99),
    ("06/08/2026", "UBER TRIP 8842", -18.20),
    ("06/09/2026", "SPOTIFY USA", -11.99),
    ("06/10/2026", "DOORDASH*THAI PALACE", -34.60),
    ("06/12/2026", "TRADER JOE'S #552", -68.13),
    ("06/13/2026", "SHELL OIL 57442199", -46.02),
    ("06/15/2026", "VERIZON WIRELESS PMT", -85.00),
    ("06/16/2026", "STARBUCKS #212", -7.10),
    ("06/18/2026", "AMAZON MKTPLACE PMTS", -63.89),
    ("06/20/2026", "PG&E UTILITY PMT", -94.32),
    ("06/21/2026", "CHIPOTLE 1123", -14.85),
    ("06/23/2026", "COMCAST XFINITY", -79.99),
    ("06/25/2026", "APPLE.COM/BILL ICLOUD", -2.99),
    ("06/27/2026", "WHOLE FOODS MKT #10233", -97.55),
    ("06/28/2026", "TARGET #2201", -52.40),
    # ---------------- July 2026 ----------------
    ("07/01/2026", "PAYROLL DEPOSIT ACME CORP", 4200.00),
    ("07/01/2026", "APEX PROPERTY MGMT RENT", -1650.00),
    ("07/02/2026", "NETFLIX.COM", -15.49),
    ("07/03/2026", "IRONWORKS FITNESS #17", -39.99),
    ("07/05/2026", "STARBUCKS #5567", -6.45),
    ("07/06/2026", "WHOLE FOODS MKT #10233", -124.88),
    ("07/07/2026", "ADOBE CREATIVE CLOUD", -54.99),
    ("07/08/2026", "DOORDASH*BURGER SHACK", -28.75),
    ("07/09/2026", "SPOTIFY USA", -11.99),
    ("07/10/2026", "UBER TRIP 9917", -22.40),
    ("07/11/2026", "TRADER JOE'S #552", -71.02),
    ("07/13/2026", "SHELL OIL 57442199", -49.60),
    ("07/15/2026", "VERIZON WIRELESS PMT", -85.00),
    ("07/16/2026", "STARBUCKS #212", -5.95),
    ("07/17/2026", "DOORDASH*PHO GARDEN", -31.20),
    ("07/19/2026", "AMAZON MKTPLACE PMTS", -41.17),
    ("07/20/2026", "PG&E UTILITY PMT", -101.76),
    ("07/22/2026", "CHIPOTLE 1123", -15.30),
    ("07/23/2026", "COMCAST XFINITY", -79.99),
    ("07/25/2026", "APPLE.COM/BILL ICLOUD", -2.99),
    ("07/26/2026", "WHOLE FOODS MKT #10233", -103.24),
    ("07/28/2026", "TARGET #2201", -38.66),
    # ---------------- August 2026 ----------------
    ("08/01/2026", "PAYROLL DEPOSIT ACME CORP", 4200.00),
    ("08/01/2026", "APEX PROPERTY MGMT RENT", -1650.00),
    ("08/02/2026", "NETFLIX.COM", -15.49),
    ("08/03/2026", "IRONWORKS FITNESS #17", -39.99),
    ("08/04/2026", "STARBUCKS #5567", -6.75),
    ("08/05/2026", "WHOLE FOODS MKT #10233", -118.31),
    ("08/07/2026", "ADOBE CREATIVE CLOUD", -54.99),
    ("08/08/2026", "DOORDASH*THAI PALACE", -36.10),
    ("08/09/2026", "SPOTIFY USA", -11.99),
    ("08/10/2026", "UBER TRIP 10233", -16.85),
    ("08/12/2026", "TRADER JOE'S #552", -64.90),
    ("08/13/2026", "SHELL OIL 57442199", -44.18),
    ("08/15/2026", "VERIZON WIRELESS PMT", -85.00),
    ("08/16/2026", "STARBUCKS #212", -6.20),
    ("08/17/2026", "DOORDASH*BURGER SHACK", -29.95),
    ("08/19/2026", "AMAZON MKTPLACE PMTS", -87.53),
    ("08/20/2026", "PG&E UTILITY PMT", -88.14),
    ("08/21/2026", "CHIPOTLE 1123", -14.85),
    ("08/23/2026", "COMCAST XFINITY", -79.99),
    ("08/25/2026", "APPLE.COM/BILL ICLOUD", -2.99),
    ("08/26/2026", "WHOLE FOODS MKT #10233", -109.47),
    ("08/27/2026", "TARGET #2201", -61.22),
]

OPENING_BALANCE = 3125.50


def fmt_money(x):
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


def make_pdf(path="sample-statement.pdf"):
    c = canvas.Canvas(path, pagesize=letter)
    width, height = letter

    left = 54
    col_desc = 130
    col_amt = 430
    col_bal = 520
    line_h = 15

    def header(page_no):
        c.setFont("Helvetica-Bold", 16)
        c.drawString(left, height - 54, "FIRST MERIDIAN BANK")
        c.setFont("Helvetica", 9)
        c.drawString(left, height - 70, "Account Statement  |  Checking ****4821")
        c.drawString(left, height - 82, "Statement period: 06/01/2026 - 08/31/2026")
        c.drawString(left, height - 94, f"Page {page_no}")
        c.line(left, height - 102, width - left, height - 102)
        c.setFont("Helvetica-Bold", 9)
        y = height - 118
        c.drawString(left, y, "Date")
        c.drawString(col_desc, y, "Description")
        c.drawRightString(col_amt + 40, y, "Amount")
        c.drawRightString(col_bal + 40, y, "Balance")
        c.line(left, y - 5, width - left, y - 5)
        c.setFont("Helvetica", 9)
        return y - line_h - 4

    page_no = 1
    y = header(page_no)

    balance = OPENING_BALANCE
    c.drawString(left, y, "06/01/2026")
    c.drawString(col_desc, y, "OPENING BALANCE")
    c.drawRightString(col_bal + 40, y, fmt_money(balance))
    y -= line_h

    for date, desc, amount in TRANSACTIONS:
        if y < 72:
            c.showPage()
            page_no += 1
            y = header(page_no)
        balance += amount
        c.drawString(left, y, date)
        c.drawString(col_desc, y, desc)
        c.drawRightString(col_amt + 40, y, fmt_money(amount))
        c.drawRightString(col_bal + 40, y, fmt_money(balance))
        y -= line_h

    if y < 100:
        c.showPage()
        page_no += 1
        y = header(page_no)
    y -= line_h
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left, y, "CLOSING BALANCE")
    c.drawRightString(col_bal + 40, y, fmt_money(balance))
    c.setFont("Helvetica", 7)
    c.drawString(left, 40, "This is a fictional statement generated for the Money Map demo project.")

    c.save()
    print(f"Wrote {path} ({len(TRANSACTIONS)} transactions, closing balance {fmt_money(balance)})")


def make_csv(path="sample-statement.csv"):
    import csv
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Description", "Amount"])
        w.writerows(TRANSACTIONS)
    print(f"Wrote {path} ({len(TRANSACTIONS)} transactions)")


if __name__ == "__main__":
    make_pdf()
    make_csv()
