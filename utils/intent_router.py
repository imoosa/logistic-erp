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

    # ── NEW INTENTS ──────────────────────────────────────────────────────────

    # Today's sales — must appear BEFORE generic sales_summary to avoid
    # "today's sales" landing on the aggregate-all-time bucket.
    (["today's sales", "todays sales", "sales today", "how much did we sell today",
      "today sale", "sales for today", "today's revenue", "today revenue",
      "today's income", "today's billing", "what did we sell today"], "todays_sales"),

    # Today's bookings
    (["today's bookings", "todays bookings", "bookings today", "how many bookings today",
      "shipments today", "today's shipments", "dispatched today",
      "today's dispatch", "today's dockets"], "todays_bookings"),

    # Overdue invoices
    (["overdue", "overdue invoice", "overdue invoices", "overdue bills",
      "pending more than 30 days", "long overdue", "which invoices are overdue",
      "which invoices are risky", "bills pending for more than",
      "invoices not paid", "long pending invoices"], "overdue_invoices"),

    # Top clients by sales
    (["top customer", "top client", "best client", "best customer",
      "highest sales client", "highest revenue client", "top 5 customer",
      "top 10 customer", "top 5 client", "top 10 client", "highest billing client",
      "which customer generated highest", "which customer generated most",
      "show my best customer"], "top_clients_sales"),

    # Top clients by outstanding
    (["who owes most", "who has highest outstanding", "highest outstanding client",
      "clients with most pending", "customer with highest balance",
      "who should i collect from first", "which customer should i follow up",
      "customer payment follow up", "collection priority"], "top_clients_outstanding"),

    # AWB / docket lookup — specific shipment search
    (["find awb", "search awb", "track awb", "awb number", "awb no",
      "find docket", "search docket", "track docket", "docket number",
      "docket no", "track shipment", "shipment status", "where is my shipment",
      "find booking", "search booking", "booking status", "track booking",
      "find invoice awb", "lookup awb", "lookup docket"], "awb_detail"),

    # Today's expenses
    (["today's expenses", "todays expenses", "expenses today", "what did we spend today",
      "today's spending", "today spending", "daily expenses today"], "todays_expenses"),

    # Expenses by category
    (["fuel expense", "fuel expenses", "salary expense", "salary expenses",
      "office expense", "office expenses", "maintenance expense", "maintenance expenses",
      "travel expense", "electricity expense", "rent expense", "misc expense",
      "expense by category", "category wise expense", "expense category"], "expenses_category"),

    # Today's cash
    (["cash today", "today's cash", "todays cash", "cash in today",
      "cash out today", "cash received today", "cash paid today",
      "today's cash flow", "cash flow today", "daily cash"], "todays_cash"),

    # Receipts and payments
    (["receipt", "receipts", "today's receipts", "monthly receipts",
      "payment received", "payments received", "collection summary",
      "money received", "amount collected", "total collection",
      "payment made", "payments made", "total payment",
      "receipts and payments", "payment summary"], "receipts_payments_summary"),

    # Client ledger / statement
    (["client statement", "customer statement", "client ledger", "customer ledger",
      "party statement", "account statement for client", "statement of account",
      "client account summary", "customer account summary",
      "client payment history", "customer payment history",
      "client invoice history", "customer invoice history"], "client_statement"),

    # Supplier ledger / statement
    (["supplier statement", "vendor statement", "supplier ledger", "vendor ledger",
      "supplier account summary", "vendor account summary",
      "supplier payment history", "supplier invoice history",
      "account statement for supplier"], "supplier_statement"),

    # Estimates / quotations
    (["estimate", "estimates", "quotation", "quotations", "quote",
      "estimate list", "show estimates", "pending estimates",
      "estimate summary", "how many estimates", "total estimates",
      "estimate value", "draft estimates"], "estimate_summary"),

    # Estimate detail (single lookup)
    (["find estimate", "show estimate", "estimate detail",
      "search estimate", "lookup estimate"], "estimate_detail"),

    # Top suppliers by purchase
    (["top supplier", "top vendor", "best supplier", "best vendor",
      "highest purchase supplier", "highest purchase vendor",
      "which supplier has highest purchase", "top 5 supplier",
      "top 10 supplier", "supplier ranking", "vendor ranking"], "top_suppliers_purchase"),

    # Destination analysis
    (["destination wise", "destination analysis", "city wise shipments",
      "city analysis", "state wise", "which city most shipments",
      "which city has highest revenue", "which destination received most",
      "top destination", "top city", "shipping city", "most shipped to",
      "where do we ship most", "destination report", "city report",
      "most profitable destination", "top shipping city"], "destination_analysis"),

    # Courier / carrier analysis
    (["courier wise", "courier analysis", "carrier analysis",
      "which courier handled most", "carrier performance",
      "courier performance", "courier comparison", "best courier",
      "which courier is best", "top courier", "courier report",
      "courier shipment count", "carrier report", "courier trend"], "courier_analysis"),

    # New clients
    (["new customer", "new customers", "new client", "new clients",
      "recently added client", "recently added customer",
      "new clients this month", "new customers this month",
      "clients added this month", "latest clients", "latest customers",
      "customer onboarding", "newly registered"], "new_clients"),

    # Customer invoice (aggregate billing)
    (["customer invoice", "billing invoice", "aggregate invoice",
      "customer invoice summary", "customer invoices",
      "billing summary", "how many customer invoices", "ci summary",
      "consolidated invoice"], "customer_invoice_summary"),

    # Bank account detail
    (["bank account detail", "account detail", "which account has highest",
      "bank transactions", "account transactions", "recent bank transactions",
      "last bank transaction", "bank account info", "show bank account"], "bank_account_detail"),

    # Pending manifests
    (["pending manifest", "pending manifests", "manifest pending",
      "manifests not dispatched", "open manifests", "unprocessed manifests",
      "manifest queue"], "pending_manifests"),

    # Help / capabilities
    (["help", "what can you do", "what can you answer", "what do you know",
      "capabilities", "list of questions", "what questions", "show help",
      "how do you help", "what can i ask", "what are your features",
      "show capabilities"], "help"),
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


def extract_limit(message: str, default: int = 10) -> int:
    """Extract a ranking limit: 'top 5', 'top 10', etc."""
    m = re.search(r"\btop\s+(\d+)\b", message.lower())
    return int(m.group(1)) if m else default


def extract_category_from_expense_message(message: str) -> str:
    """Extract expense category from message (fuel, salary, office, etc.)."""
    msg = message.lower()
    categories = [
        "fuel", "salary", "office", "maintenance", "travel",
        "electricity", "rent", "misc", "miscellaneous", "repair",
        "transport", "printing", "insurance", "telephone", "internet",
        "water", "cleaning", "stationary", "food",
    ]
    for cat in categories:
        if cat in msg:
            return cat
    return ""


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
