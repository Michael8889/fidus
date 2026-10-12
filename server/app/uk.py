"""UK pack: VAT numbers on receipts and the UK tax calendar as reminders.

Deadlines (gov.uk / HMRC rules, checked Oct 2026): Self Assessment online return and payment 31 January, second
payment on account 31 July; MTD for Income Tax (income over £50,000 from April 2026) quarterly updates by 7 Aug,
7 Nov, 7 Feb and 7 May; VAT return and payment one calendar month and 7 days after the period ends; Corporation Tax
payment 9 months and 1 day after the accounting period, CT600 12 months after; Companies House accounts 9 months after
the year end and the confirmation statement within 14 days of the review date; PAYE paid by the 22nd (electronic).
Reminders fire a few days BEFORE each deadline, so they stay right every year. Nothing here replaces an accountant.
"""
from datetime import date, datetime, timedelta

from . import features, store


def valid_vat(number: str | None) -> bool:
    """UK VAT registration number: GB + 9 digits with the HMRC check (mod 97, old and new series)."""
    d = "".join(ch for ch in (number or "") if ch.isdigit())
    if len(d) != 9:
        return False
    total = sum(int(d[i]) * (8 - i) for i in range(7)) + int(d[7:])
    return total % 97 == 0 or (total + 55) % 97 == 0


def vat_registered() -> bool:
    return bool(store.profile().get("uk_vat_registered"))


def check_receipt(currency: str, vat: float | None, supplier_vat: str | None) -> list[str]:
    if currency != "GBP":
        return []
    out = []
    if supplier_vat and not valid_vat(supplier_vat):
        out.append("the supplier's VAT number on the receipt doesn't look valid; check the photo")
    elif vat_registered() and vat and not supplier_vat:
        out.append("this receipt shows VAT but no supplier VAT number: you may not be able to reclaim that VAT. "
                   "Ask for a full VAT invoice")
    return out


def _next(month: int, day: int) -> date:
    today = date.today()
    d = date(today.year, month, day)
    return d if d >= today else date(today.year + 1, month, day)


def _next_monthly(day: int) -> date:
    today = date.today()
    d = today.replace(day=day)
    if d < today:
        d = (today.replace(day=1) + timedelta(days=32)).replace(day=day)
    return d


def _add_months(m: int, k: int) -> int:
    return (m - 1 + k) % 12 + 1


def _plan(self_employed: bool, payments_on_account: bool, mtd_itsa: bool, vat_quarter_ends: list[int],
          company_year_end: int | None, confirmation_month: int | None, employees: bool):
    items = []
    if self_employed:
        items.append(("Self Assessment: file online and pay by 31 January", _next(1, 10), "RRULE:FREQ=YEARLY",
                      "Includes the first payment on account for the new tax year, if you have them."))
        items.append(("Self Assessment: new tax year starts 6 April, keep your records", _next(4, 6), "RRULE:FREQ=YEARLY", None))
    if payments_on_account:
        items.append(("Self Assessment: second payment on account due 31 July", _next(7, 20), "RRULE:FREQ=YEARLY", None))
    if mtd_itsa:
        for m in (8, 11, 2, 5):
            items.append(("Making Tax Digital: quarterly update due by the 7th", _next(m, 1), "RRULE:FREQ=YEARLY",
                          "MTD for Income Tax (sole traders and landlords over the threshold)."))
    for q in vat_quarter_ends:
        due_month = _add_months(q, 2)
        items.append((f"VAT return and payment due by the 7th (quarter ending {date(2000, q, 1):%B})",
                      _next(due_month, 1), "RRULE:FREQ=YEARLY", "Due one calendar month and 7 days after the quarter ends."))
    if company_year_end:
        y = int(company_year_end)
        items.append(("Companies House: annual accounts due by the end of this month", _next(_add_months(y, 9), 1),
                      "RRULE:FREQ=YEARLY", "9 months after the financial year end."))
        items.append(("Corporation Tax: payment due on the 1st of next month", _next(_add_months(y, 9), 15),
                      "RRULE:FREQ=YEARLY", "9 months and 1 day after the accounting period ends."))
        items.append(("Corporation Tax return (CT600) due by the end of this month", _next(_add_months(y, 12), 1),
                      "RRULE:FREQ=YEARLY", "12 months after the accounting period ends."))
    if confirmation_month:
        items.append(("Companies House: confirmation statement (within 14 days of the review date)",
                      _next(int(confirmation_month), 1), "RRULE:FREQ=YEARLY", None))
    if employees:
        items.append(("PAYE: pay HMRC by the 22nd", _next_monthly(18), "RRULE:FREQ=MONTHLY", None))
    return items


def set_uk_tax_profile(vat_registered: bool | None = None) -> dict:
    if vat_registered is not None:
        store.save_profile(uk_vat_registered=bool(vat_registered) or "")
    return {"ok": True, "vat_registered": bool(store.profile().get("uk_vat_registered"))}


def setup_uk_tax_reminders(self_employed: bool = False, payments_on_account: bool = False, mtd_itsa: bool = False,
                           vat_quarter_ends: list | None = None, company_year_end: int | None = None,
                           confirmation_month: int | None = None, employees: bool = False) -> dict:
    qs = sorted({int(m) for m in (vat_quarter_ends or []) if str(m).isdigit() and 1 <= int(m) <= 12})
    if qs:
        set_uk_tax_profile(True)
    done = store.profile().get("uk_tax_reminders") or []
    created, skipped = [], 0
    for text, first, rrule, note in _plan(self_employed, payments_on_account, mtd_itsa, qs,
                                          int(company_year_end) if company_year_end else None,
                                          int(confirmation_month) if confirmation_month else None, employees):
        key = f"{text}|{first.month}"
        if key in done:
            skipped += 1
            continue
        r = features.create_reminder(text, datetime(first.year, first.month, first.day, 9, 0).isoformat(), rrule, note)
        created.append({"text": text, "first": first.isoformat(), "event_id": r.get("event_id")})
        done.append(key)
    store.save_profile(uk_tax_reminders=done)
    return {"ok": True, "created": created, "already_existed": skipped,
            "note": "Reminders a few days before each deadline, every year. If a deadline falls on a weekend, pay "
                    "earlier (HMRC needs the money by then). Check your own dates with your accountant."}


TOOLS = [
    {
        "name": "setup_uk_tax_reminders",
        "description": "UK: creates recurring reminders for the UK tax calendar (Self Assessment, payments on account, "
                       "MTD for Income Tax, VAT, Corporation Tax, Companies House, PAYE). Ask first: self-employed?, "
                       "payments on account?, MTD for Income Tax?, VAT quarter end months (e.g. 3,6,9,12) if VAT "
                       "registered, company year-end month, confirmation statement month, employees? No duplicates.",
        "parameters": {"type": "object", "properties": {
            "self_employed": {"type": "boolean"}, "payments_on_account": {"type": "boolean"},
            "mtd_itsa": {"type": "boolean"},
            "vat_quarter_ends": {"type": "array", "items": {"type": "integer"}},
            "company_year_end": {"type": "integer", "description": "month 1-12 of the company's financial year end"},
            "confirmation_month": {"type": "integer"}, "employees": {"type": "boolean"},
        }},
    },
    {
        "name": "set_uk_tax_profile",
        "description": "UK: records whether the user is VAT registered (Fidus then checks VAT numbers on receipts).",
        "parameters": {"type": "object", "properties": {"vat_registered": {"type": "boolean"}}},
    },
]

DISPATCH = {"setup_uk_tax_reminders": setup_uk_tax_reminders, "set_uk_tax_profile": set_uk_tax_profile}
