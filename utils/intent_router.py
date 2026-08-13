"""
intent_router.py  (Logistics ERP / Magnustic ERP version)
────────────────────────────────────────────────────────
Deterministic keyword → function dispatch. No AI involved in routing.
company_id ALWAYS comes from the logged-in session server-side — this
router never accepts or infers a company_id from the message text. If
that guarantee breaks (e.g. someone wires this to accept company_id from
a request body instead of session), the isolation this whole module was
built for is gone. Don't do that.
"""

import re
from typing import Optional, Dict, Any


INTENT_MAP = [
    # GST / Tax — checked FIRST, before every other bucket. This is
    # deliberate: "total purchase tax" previously matched the "total
    # purchase" keyword in purchase_summary below and got an unrelated
    # number relabeled as tax. Putting GST/tax at the very top means it
    # always wins that race regardless of what other keywords get added
    # later.
    (["gst payable", "gst receivable", "cgst", "sgst", "igst", "gst report",
      "gst collected", "gst paid", "input tax", "output tax", "gst liability",
      "tax payable", "tax receivable", "purchase tax", "sales tax", "total tax",
      "quarterly gst", "monthly gst", "yearly gst", "gst summary", "tax summary",
      "what is my gst", "how much gst", "how much tax do i owe", "gst"],
     "gst_summary"),

    # Receivables / payables — before generic invoice/client keywords
    (["who owes", "outstanding receivable", "pending receivable", "receivables",
      "unpaid invoices", "clients pending", "who has to pay", "money is pending",
      "amount receivable", "who has not paid", "total receivable",
      "customers with highest outstanding", "overdue invoices",
      "bills pending", "who should i collect from",
      "total amount pending", "pending amount to be received",
      "pending amount to receive", "balance pending amount to be received",
      "balance pending to receive", "total pending amount to receive",
      "amount to be received", "how much amount is pending to receive",
      "how much do i need to collect"], "pending_receivables"),

    (["who do we owe", "outstanding payable", "pending payable", "payables",
      "unpaid purchase", "suppliers pending", "we owe", "amount payable",
      "total payable", "suppliers with highest payable",
      "which supplier should i pay",
      "pending amount to pay", "balance pending to pay",
      "amount to be paid", "how much do i need to pay",
      "how much amount is pending to pay"], "pending_payables"),

    # Sales — before generic invoice/dashboard keywords, so "total sales" /
    # "revenue" don't fall through to the generic invoice_detail bucket.
    (["total sales", "sales summary", "how much did we sell", "sales figure",
      "our sales", "my sales", "total revenue", "revenue", "turnover", "income",
      "sales this month", "sales report", "sales amount", "did we earn",
      "how much money did we make", "earnings", "billing", "customer sales",
      "invoice sales", "highest invoice", "lowest invoice", "invoice summary",
      "compare this month and last month sales", "average sales per day",
      "which day had highest sales"], "sales_summary"),

    # Purchase — mirrors sales_summary; must come before the generic
    # "purchase invoice" bucket below so "total purchase"/"monthly purchase"
    # (no specific invoice number) land on the aggregate, not a lookup.
    # gst_summary above already intercepts anything with "tax" in it, so
    # "total purchase tax" no longer reaches this bucket.
    (["total purchase", "monthly purchase", "today's purchase", "purchase trend",
      "purchase summary", "purchase report", "buying", "procurement",
      "vendor purchase", "supplier purchase", "compare purchases month wise",
      "highest supplier purchase", "lowest supplier purchase"], "purchase_summary"),

    # Cash / bank — before "amount"/"balance" generic terms
    (["cash in hand", "cash balance", "cash summary", "how much cash",
      "petty cash", "cashbook", "cash book", "cash report", "today's cash",
      "cash received", "cash paid"], "cash_summary"),
    (["bank balance", "bank summary", "bank account balance", "how much in bank",
      "bank statement", "bank ledger", "deposit", "withdrawal",
      "bank transaction"], "bank_summary"),

    # Loans / cheques
    (["loan", "emi", "loan outstanding", "loan balance", "borrowing",
      "repayment", "interest paid"], "loans_summary"),
    (["cheque", "check pending", "cheque status", "cheques pending",
      "cleared cheque", "bounced cheque", "cheque due"], "cheques_summary"),

    # Expenses
    (["expense", "expenses", "spend on", "spending", "fuel expense",
      "office expense", "salary expense", "maintenance expense",
      "expense category", "expense trend", "biggest expense",
      "which expense is increasing"], "expenses_summary"),

    # Manifest
    (["manifest", "boxes received", "courier allocation"], "manifest_summary"),

    # Stock — item detail vs. general summary decided in dispatch()
    (["stock", "inventory", "low stock", "reorder", "warehouse", "out of stock",
      "stock valuation", "stock movement", "fast moving stock",
      "slow moving stock", "dead stock", "most sold item", "least sold item",
      "how much stock"], "stock_summary"),

    # Purchase invoices — before generic "invoice"
    (["purchase invoice", "purchase bill", "supplier invoice", "purchase order"], "purchase_invoice_detail"),

    # Sales invoices
    (["invoice", "booking invoice", "awb", "docket"], "invoice_detail"),

    # Suppliers — before clients (avoid "supplier" containing "client"-like false hits)
    (["supplier", "vendor"], "supplier_lookup"),

    # Clients
    (["client", "customer", "debtor"], "client_lookup"),

    # Dashboard / overview
    (["dashboard", "overview", "how is business", "give me a summary",
      "how are we doing", "business summary", "today's summary",
      "company overview", "today's activity", "current business status",
      "how is business today", "performance", "analytics"], "dashboard_summary"),

      (["net profit", "our net profit", "profit and loss", "p&l", "p and l",
      "how much profit", "total profit", "profit this month", "profit summary",
      "profit report", "are we profitable", "profit margin"], "net_profit_summary"),
 
    (["gross profit", "gross margin", "total gross profit",
      "gross profit summary", "gross profit report"], "gross_profit_summary"),
 
    (["list of bookings", "all bookings", "booking list", "show bookings",
      "recent bookings", "bookings today", "bookings this month",
      "how many bookings"], "bookings_list"),
 
    (["void", "voided", "void invoice", "void booking", "void bookings",
      "cancelled invoice", "cancelled invoices", "cancelled booking",
      "cancelled bookings", "list of cancelled", "list of void",
      "how many cancelled", "how many void"], "void_cancelled_list"),
 
    (["how many clients", "total clients", "client count", "no of clients",
      "number of clients"], "client_count"),
 
    (["how many suppliers", "total suppliers", "supplier count",
      "no of suppliers", "number of suppliers"], "supplier_count"),
 
    (["price list uploaded", "last price list", "price list date",
      "when was price list", "price list update", "company price list",
      "price list for", "rate list uploaded", "rate list date"], "price_list_status"),
 
    (["whatsapp connected", "is whatsapp connected", "whatsapp status",
      "whatsapp working", "whatsapp integration status",
      "check whatsapp"], "whatsapp_status"),
 
    (["how many users", "total users", "user count", "no of users",
      "number of users", "how many owners", "owner count",
      "how many employees", "employee count", "users in company",
      "staff count", "list of users", "list of employees"], "user_count_summary"),
]


def classify_intent(message: str) -> Optional[str]:
    msg = message.lower()
    for keywords, intent in INTENT_MAP:
        if any(kw in msg for kw in keywords):
            return intent
    return None


# Filler words to strip so what remains is a name/code/AWB/etc.
_FILLER = re.compile(
    r"(?i)\b("
    r"tell me about|details of|info on|information on|what is|what's|"
    r"show me|give me|find|search|lookup|look up|"
    r"client|customer|supplier|vendor|invoice|purchase invoice|purchase bill|"
    r"stock item|item|awb|docket|manifest|"
    r"the|my|our|please|for|of|status|detail|details|about"
    r")\b"
)


def _clean_identifier(message: str) -> str:
    cleaned = _FILLER.sub("", message)
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_months(message: str, default: int = 1) -> int:
    msg = message.lower()
    if "3 month" in msg or "quarter" in msg or "last 3" in msg:
        return 3
    if "6 month" in msg or "half year" in msg:
        return 6
    if "12 month" in msg or "year" in msg or "annual" in msg:
        return 12
    return default


def extract_days(message: str, default: int = 30) -> int:
    m = re.search(r"(\d+)\s*day", message.lower())
    return int(m.group(1)) if m else default


# ─────────────────────────────────────────────────────────────────────────
# Main dispatch — company_id must be passed in by the caller, sourced from
# the authenticated session, never from message text.
# ─────────────────────────────────────────────────────────────────────────

def dispatch(message: str, company_id: str) -> Dict[str, Any]:
    from utils.query_engine import (
        get_dashboard_summary, get_client_detail, get_all_clients_summary,
        get_supplier_detail, get_all_suppliers_summary, get_invoice_detail,
        get_pending_receivables, get_pending_payables, get_purchase_invoice_detail,
        get_cash_summary, get_bank_summary, get_expenses_summary,
        get_stock_summary, get_stock_item_detail, get_manifest_summary,
        get_loans_summary, get_cheques_summary, get_sales_summary,
        get_purchase_summary, get_gst_summary,
        # NEW — these 9 were being called below with no import at all,
        # which meant every one of them raised NameError at runtime:
        get_net_profit_summary, get_gross_profit_summary, get_bookings_list,
        get_void_cancelled_list, get_client_count, get_supplier_count,
        get_price_list_status, get_whatsapp_status, get_user_count_summary,
    )

    if not company_id:
        # Defensive: never silently query without a scoped company.
        return {"intent": None, "error": "no_company_context", "message": message}

    msg_lower = message.lower()
    intent = classify_intent(message)
    print(f"[ROUTER] company={company_id} message='{message[:60]}' intent='{intent}'")

    if intent is None:
        return {"intent": None, "message": message}

    if intent == "dashboard_summary":
        return get_dashboard_summary(company_id)

    if intent == "sales_summary":
        # default=None → all-time total unless the user names a period
        months = extract_months(message, default=None)
        return get_sales_summary(company_id, months=months)

    if intent == "purchase_summary":
        months = extract_months(message, default=None)
        return get_purchase_summary(company_id, months=months)

    if intent == "gst_summary":
        # NOTE: /api/reports/tax-data defaults to the current month when no
        # date range is passed; this chat path defaults to all-time instead
        # (same convention as sales_summary/purchase_summary above) unless
        # the user names a period. That means the number the chatbot gives
        # for a bare "what's my GST payable" can legitimately differ from
        # whatever range is currently applied on the Tax/GST Report tab —
        # that's a real discrepancy in default period, not a bug in either
        # place, but it will confuse someone comparing the two side by side.
        months = extract_months(message, default=None)
        return get_gst_summary(company_id, months=months)

    if intent == "client_lookup":
        identifier = _clean_identifier(message)
        if any(kw in msg_lower for kw in ["all client", "list client", "how many client", "total client"]):
            return get_all_clients_summary(company_id)
        if identifier and len(identifier) >= 2:
            result = get_client_detail(company_id, identifier)
            if result.get("found"):
                return result
        return get_all_clients_summary(company_id)

    if intent == "supplier_lookup":
        identifier = _clean_identifier(message)
        if any(kw in msg_lower for kw in ["all supplier", "list supplier", "how many supplier", "total supplier"]):
            return get_all_suppliers_summary(company_id)
        if identifier and len(identifier) >= 2:
            result = get_supplier_detail(company_id, identifier)
            if result.get("found"):
                return result
        return get_all_suppliers_summary(company_id)

    if intent == "invoice_detail":
        identifier = _clean_identifier(message)
        if identifier and len(identifier) >= 2:
            result = get_invoice_detail(company_id, identifier)
            if result.get("found"):
                return result
        return get_pending_receivables(company_id)

    if intent == "purchase_invoice_detail":
        identifier = _clean_identifier(message)
        if identifier and len(identifier) >= 2:
            result = get_purchase_invoice_detail(company_id, identifier)
            if result.get("found"):
                return result
        return get_pending_payables(company_id)

    if intent == "pending_receivables":
        return get_pending_receivables(company_id)

    if intent == "pending_payables":
        return get_pending_payables(company_id)

    if intent == "cash_summary":
        return get_cash_summary(company_id)

    if intent == "bank_summary":
        return get_bank_summary(company_id)

    if intent == "expenses_summary":
        months = extract_months(message)
        return get_expenses_summary(company_id, months=months)

    if intent == "stock_summary":
        identifier = _clean_identifier(message)
        if identifier and len(identifier) >= 2 and not any(
            kw in msg_lower for kw in ["low stock", "reorder", "all stock", "total stock"]
        ):
            result = get_stock_item_detail(company_id, identifier)
            if result.get("found"):
                return result
        return get_stock_summary(company_id)

    if intent == "manifest_summary":
        days = extract_days(message, default=30)
        return get_manifest_summary(company_id, days=days)

    if intent == "loans_summary":
        return get_loans_summary(company_id)

    if intent == "cheques_summary":
        return get_cheques_summary(company_id)

    if intent == "net_profit_summary":
        months = extract_months(message, default=None)
        return get_net_profit_summary(company_id, months=months)
 
    if intent == "gross_profit_summary":
        months = extract_months(message, default=None)
        return get_gross_profit_summary(company_id, months=months)
 
    if intent == "bookings_list":
        # reuse extract_days for "bookings this month" style ranges;
        # confirm with Ibrahim what date field bookings should filter on
        days = extract_days(message, default=30)
        return get_bookings_list(company_id, days=days)
 
    if intent == "void_cancelled_list":
        days = extract_days(message, default=30)
        return get_void_cancelled_list(company_id, days=days)
 
    if intent == "client_count":
        return get_client_count(company_id)
 
    if intent == "supplier_count":
        return get_supplier_count(company_id)
 
    if intent == "price_list_status":
        # if the message names a specific company/supplier, pass it through;
        # get_price_list_status decides per-company vs. all-companies view
        identifier = _clean_identifier(message)
        return get_price_list_status(company_id, identifier or None)
 
    if intent == "whatsapp_status":
        return get_whatsapp_status(company_id)
 
    if intent == "user_count_summary":
        # get_user_count_summary should return counts segregated by role,
        # e.g. {"owners": n, "managers": n, "employees": n, "total": n}
        return get_user_count_summary(company_id)

    print(f"[ROUTER] WARNING: unhandled intent '{intent}'")
    return {"intent": None, "message": message}
