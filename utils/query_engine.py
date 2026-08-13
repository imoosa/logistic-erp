"""
query_engine.py  (Logistics ERP / Magnustic ERP version)
──────────────────────────────────────────────────────────
Every function takes `company_id` and gets its session via
db_router.get_customer_session(company_id) — the same cached,
per-company session app.py's own routes use (get_cdb()).

We do NOT close the session at the end of each function. app.py's
teardown_request already owns that session's lifecycle (rollback on
error); closing it here would fight that and could poison the session
for whatever route/request touches this company next. If you call this
from a route, just use get_cdb() / get_customer_session(company_id) the
same way the rest of app.py does.

Isolation note: customer_models.py has no Flask-SQLAlchemy `.query`
shortcut — the only way to reach data at all is through the session
requested here, which is physically bound to erp_<company_id>'s own
MySQL database. company_id filters below are belt-and-suspenders on
top of that, matching the existing column-per-table convention.
"""

from datetime import timedelta, date
from typing import Dict, Any
from sqlalchemy import func

from db_router import get_customer_session
from customer_models import (
    Client, Supplier, Invoice, PurchaseInvoice, StockItem, CashTransaction,
    BankAccount, Loan, Cheque, CompanyManifest, Expense,
)


# ─────────────────────────────────────────────────────────────────────────
# Dashboard / overview
# ─────────────────────────────────────────────────────────────────────────

def get_dashboard_summary(company_id: str) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)

    total_clients = cdb.query(Client).filter_by(company_id=company_id).count()
    total_suppliers = cdb.query(Supplier).filter_by(company_id=company_id).count()

    pending_invoices = (
        cdb.query(Invoice)
        .filter(Invoice.company_id == company_id, Invoice.status != "Paid")
        .count()
    )
    total_receivable = (
        cdb.query(func.sum(Invoice.balance))
        .filter(Invoice.company_id == company_id, Invoice.balance > 0)
        .scalar() or 0.0
    )
    total_payable = (
        cdb.query(func.sum(PurchaseInvoice.balance))
        .filter(PurchaseInvoice.company_id == company_id, PurchaseInvoice.balance > 0)
        .scalar() or 0.0
    )
    cash_balance = _cash_balance(cdb, company_id)
    bank_balance = (
        cdb.query(func.sum(BankAccount.balance))
        .filter(BankAccount.company_id == company_id, BankAccount.status == "Active")
        .scalar() or 0.0
    )

    this_month_start = date.today().replace(day=1)
    month_sales = (
        cdb.query(func.sum(Invoice.grand_total))
        .filter(Invoice.company_id == company_id, Invoice.date >= this_month_start)
        .scalar() or 0.0
    )

    return {
        "intent": "dashboard_summary",
        "total_clients": total_clients,
        "total_suppliers": total_suppliers,
        "pending_invoices": pending_invoices,
        "total_receivable": round(total_receivable, 2),
        "total_payable": round(total_payable, 2),
        "cash_balance": round(cash_balance, 2),
        "bank_balance": round(bank_balance, 2),
        "this_month_sales": round(month_sales, 2),
    }


# ─────────────────────────────────────────────────────────────────────────
# Clients
# ─────────────────────────────────────────────────────────────────────────

def get_client_detail(company_id: str, identifier: str) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    ident = f"%{identifier.strip()}%"
    client = (
        cdb.query(Client)
        .filter(
            Client.company_id == company_id,
            (Client.name.ilike(ident)) |
            (Client.client_id.ilike(ident)) |
            (Client.phone.ilike(ident)),
        )
        .first()
    )
    if not client:
        return {"intent": "client_detail", "found": False, "query": identifier}

    return {
        "intent": "client_detail",
        "found": True,
        "name": client.name,
        "client_id": client.client_id,
        "client_type": client.client_type,
        "phone": client.phone,
        "email": client.email,
        "city": client.city,
        "state": client.state,
        "gst_number": client.gst_number,
        "gst_type": client.gst_type,
        "credit_limit": client.credit_limit,
        "credit_days": client.credit_days,
        "pending_amount": client.pending,
        "status": client.status,
    }


def get_all_clients_summary(company_id: str) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    clients = cdb.query(Client).filter_by(company_id=company_id).all()
    total_pending = sum(c.pending or 0 for c in clients)
    active = sum(1 for c in clients if (c.status or "").lower() == "active")
    return {
        "intent": "all_clients_summary",
        "total_clients": len(clients),
        "active_clients": active,
        "total_pending_receivable": round(total_pending, 2),
        "top_pending": sorted(
            [{"name": c.name, "pending": c.pending} for c in clients if c.pending],
            key=lambda x: x["pending"], reverse=True
        )[:10],
    }


# ─────────────────────────────────────────────────────────────────────────
# Suppliers
# ─────────────────────────────────────────────────────────────────────────

def get_supplier_detail(company_id: str, identifier: str) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    ident = f"%{identifier.strip()}%"
    supplier = (
        cdb.query(Supplier)
        .filter(
            Supplier.company_id == company_id,
            (Supplier.name.ilike(ident)) |
            (Supplier.supplier_id.ilike(ident)) |
            (Supplier.phone.ilike(ident)),
        )
        .first()
    )
    if not supplier:
        return {"intent": "supplier_detail", "found": False, "query": identifier}

    return {
        "intent": "supplier_detail",
        "found": True,
        "name": supplier.name,
        "supplier_id": supplier.supplier_id,
        "supplier_type": supplier.supplier_type,
        "phone": supplier.phone,
        "email": supplier.email,
        "gst_number": supplier.gst_number,
        "gst_type": supplier.gst_type,
        "credit_limit": supplier.credit_limit,
        "payable_amount": supplier.payable,
        "status": supplier.status,
        "brands": [b.brand_name for b in supplier.brands],
    }


def get_all_suppliers_summary(company_id: str) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    suppliers = cdb.query(Supplier).filter_by(company_id=company_id).all()
    total_payable = sum(s.payable or 0 for s in suppliers)
    return {
        "intent": "all_suppliers_summary",
        "total_suppliers": len(suppliers),
        "total_payable": round(total_payable, 2),
        "top_payable": sorted(
            [{"name": s.name, "payable": s.payable} for s in suppliers if s.payable],
            key=lambda x: x["payable"], reverse=True
        )[:10],
    }


# ─────────────────────────────────────────────────────────────────────────
# Sales invoices
# ─────────────────────────────────────────────────────────────────────────

def get_invoice_detail(company_id: str, invoice_identifier: str) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    ident = f"%{invoice_identifier.strip()}%"
    inv = (
        cdb.query(Invoice)
        .filter(Invoice.company_id == company_id, Invoice.invoice_id.ilike(ident))
        .first()
    )
    if not inv:
        return {"intent": "invoice_detail", "found": False, "query": invoice_identifier}

    client = cdb.query(Client).filter_by(id=inv.client_id).first()
    return {
        "intent": "invoice_detail",
        "found": True,
        "invoice_id": inv.invoice_id,
        "client": client.name if client else "Unknown",
        "date": inv.date.strftime("%d %b %Y"),
        "status": inv.status,
        "subtotal": inv.subtotal,
        "tax_amount": inv.tax_amount,
        "grand_total": inv.grand_total,
        "paid_amount": inv.paid_amount,
        "balance": inv.balance,
    }


def get_sales_summary(company_id: str, months: int = None) -> Dict[str, Any]:
    """
    Total sales from the Invoice table (this is the sales/booking invoice
    model — see PurchaseInvoice below for the separate payables side).
    months=None → all-time total. months=N → last N*30 days only.
    """
    cdb = get_customer_session(company_id)
    q = cdb.query(Invoice).filter(Invoice.company_id == company_id)
    if months:
        cutoff = date.today() - timedelta(days=30 * months)
        q = q.filter(Invoice.date >= cutoff)
    rows = q.all()

    total_sales = sum(inv.grand_total or 0 for inv in rows)
    total_collected = sum(inv.paid_amount or 0 for inv in rows)
    total_pending = sum(inv.balance or 0 for inv in rows)

    return {
        "intent": "sales_summary",
        "period_months": months,   # None means all-time
        "invoice_count": len(rows),
        "total_sales": round(total_sales, 2),
        "total_collected": round(total_collected, 2),
        "total_pending": round(total_pending, 2),
    }


def get_pending_receivables(company_id: str, limit: int = 15) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    rows = (
        cdb.query(Invoice)
        .filter(Invoice.company_id == company_id, Invoice.balance > 0)
        .order_by(Invoice.balance.desc())
        .limit(limit)
        .all()
    )
    total = (
        cdb.query(func.sum(Invoice.balance))
        .filter(Invoice.company_id == company_id, Invoice.balance > 0)
        .scalar() or 0.0
    )
    items = []
    for inv in rows:
        client = cdb.query(Client).filter_by(id=inv.client_id).first()
        items.append({
            "invoice_id": inv.invoice_id,
            "client": client.name if client else "Unknown",
            "balance": inv.balance,
            "due_date": inv.due_date.strftime("%d %b %Y") if inv.due_date else None,
            "overdue": bool(inv.due_date and inv.due_date < date.today()),
        })
    return {
        "intent": "pending_receivables",
        "count": len(items),
        "total_outstanding": round(total, 2),
        "items": items,
    }


def get_pending_payables(company_id: str, limit: int = 15) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    rows = (
        cdb.query(PurchaseInvoice)
        .filter(PurchaseInvoice.company_id == company_id, PurchaseInvoice.balance > 0)
        .order_by(PurchaseInvoice.balance.desc())
        .limit(limit)
        .all()
    )
    total = (
        cdb.query(func.sum(PurchaseInvoice.balance))
        .filter(PurchaseInvoice.company_id == company_id, PurchaseInvoice.balance > 0)
        .scalar() or 0.0
    )
    items = [{
        "invoice_id": p.invoice_id,
        "supplier": p.supplier_name,
        "balance": p.balance,
        "due_date": p.due_date.strftime("%d %b %Y") if p.due_date else None,
        "overdue": bool(p.due_date and p.due_date < date.today()),
    } for p in rows]
    return {
        "intent": "pending_payables",
        "count": len(items),
        "total_outstanding": round(total, 2),
        "items": items,
    }


# ─────────────────────────────────────────────────────────────────────────
# GST / Tax
# Mirrors app.py's /api/reports/tax-data endpoint exactly: same status
# exclusion on sales (Cancelled/Void), same tax_amount fields, same
# output_gst - input_gst = net_gst formula. Deliberately NOT reusing the
# HSN-level cgst/sgst/igst split from that endpoint here — that's computed
# per-invoice-item there and isn't worth duplicating for a chat summary;
# cgst/sgst below use the same output_gst/2 approximation the report route
# itself uses (it hardcodes igst to 0 too — an existing simplification in
# tax-data, not something introduced here).
# ─────────────────────────────────────────────────────────────────────────

def get_gst_summary(company_id: str, months: int = None) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)

    sales_q = cdb.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.status.notin_(['Cancelled', 'Void']),
    )
    purchase_q = cdb.query(PurchaseInvoice).filter(PurchaseInvoice.company_id == company_id)

    if months:
        cutoff = date.today() - timedelta(days=30 * months)
        sales_q = sales_q.filter(Invoice.date >= cutoff)
        purchase_q = purchase_q.filter(PurchaseInvoice.date >= cutoff)

    sales = sales_q.all()
    purchases = purchase_q.all()

    output_gst = sum(float(i.tax_amount or 0) for i in sales)
    input_gst = sum(float(p.tax_amount or 0) for p in purchases)
    net_gst = output_gst - input_gst

    return {
        "intent": "gst_summary",
        "period_months": months,  # None means all-time
        "output_gst": round(output_gst, 2),      # GST collected on sales
        "input_gst": round(input_gst, 2),        # GST paid on purchases
        "net_gst": round(net_gst, 2),
        "net_gst_status": "payable" if net_gst > 0 else ("receivable" if net_gst < 0 else "nil"),
        "cgst": round(output_gst / 2, 2),
        "sgst": round(output_gst / 2, 2),
        "igst": 0.0,
    }


# ─────────────────────────────────────────────────────────────────────────
# Purchase invoices
# ─────────────────────────────────────────────────────────────────────────

def get_purchase_summary(company_id: str, months: int = None) -> Dict[str, Any]:
    """
    Aggregate purchase totals from PurchaseInvoice — the purchase-side
    mirror of get_sales_summary(). months=None → all-time; months=N →
    last N*30 days only.
    """
    cdb = get_customer_session(company_id)
    q = cdb.query(PurchaseInvoice).filter(PurchaseInvoice.company_id == company_id)
    if months:
        cutoff = date.today() - timedelta(days=30 * months)
        q = q.filter(PurchaseInvoice.date >= cutoff)
    rows = q.all()

    total_purchase = sum(p.grand_total or 0 for p in rows)
    total_paid = sum(p.paid_amount or 0 for p in rows)
    total_pending = sum(p.balance or 0 for p in rows)

    return {
        "intent": "purchase_summary",
        "period_months": months,
        "invoice_count": len(rows),
        "total_purchase": round(total_purchase, 2),
        "total_paid": round(total_paid, 2),
        "total_pending": round(total_pending, 2),
    }


def get_purchase_invoice_detail(company_id: str, identifier: str) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    ident = f"%{identifier.strip()}%"
    p = (
        cdb.query(PurchaseInvoice)
        .filter(PurchaseInvoice.company_id == company_id, PurchaseInvoice.invoice_id.ilike(ident))
        .first()
    )
    if not p:
        return {"intent": "purchase_invoice_detail", "found": False, "query": identifier}
    return {
        "intent": "purchase_invoice_detail",
        "found": True,
        "invoice_id": p.invoice_id,
        "supplier": p.supplier_name,
        "date": p.date.strftime("%d %b %Y"),
        "status": p.status,
        "grand_total": p.grand_total,
        "paid_amount": p.paid_amount,
        "balance": p.balance,
    }


# ─────────────────────────────────────────────────────────────────────────
# Cash / Bank
# CashTransaction.type is 'income' / 'expense' (matches app.py's own
# filters elsewhere, e.g. api_dashboard_data) — NOT 'in' / 'out'.
# ─────────────────────────────────────────────────────────────────────────

def _cash_balance(cdb, company_id: str) -> float:
    income_total = (
        cdb.query(func.sum(CashTransaction.amount))
        .filter(CashTransaction.company_id == company_id, CashTransaction.type == "income")
        .scalar() or 0.0
    )
    expense_total = (
        cdb.query(func.sum(CashTransaction.amount))
        .filter(CashTransaction.company_id == company_id, CashTransaction.type == "expense")
        .scalar() or 0.0
    )
    return income_total - expense_total


def get_cash_summary(company_id: str) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    balance = _cash_balance(cdb, company_id)
    this_month_start = date.today().replace(day=1)
    month_out = (
        cdb.query(func.sum(CashTransaction.amount))
        .filter(
            CashTransaction.company_id == company_id,
            CashTransaction.type == "expense",
            CashTransaction.date >= this_month_start,
        ).scalar() or 0.0
    )
    return {
        "intent": "cash_summary",
        "cash_balance": round(balance, 2),
        "this_month_cash_out": round(month_out, 2),
    }


def get_bank_summary(company_id: str) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    accounts = cdb.query(BankAccount).filter_by(company_id=company_id, status="Active").all()
    total = sum(a.balance or 0 for a in accounts)
    return {
        "intent": "bank_summary",
        "total_balance": round(total, 2),
        "accounts": [
            {"bank_name": a.bank_name,
             "account_number": a.account_number[-4:].rjust(len(a.account_number), '*'),
             "balance": a.balance} for a in accounts
        ],
    }


# ─────────────────────────────────────────────────────────────────────────
# Expenses
# ─────────────────────────────────────────────────────────────────────────

def get_expenses_summary(company_id: str, months: int = 1) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    cutoff = date.today() - timedelta(days=30 * months)
    rows = (
        cdb.query(Expense.category, func.sum(Expense.amount))
        .filter(Expense.company_id == company_id, Expense.date >= cutoff)
        .group_by(Expense.category)
        .all()
    )
    total = sum(amt for _, amt in rows)
    return {
        "intent": "expenses_summary",
        "period_months": months,
        "total_expenses": round(total, 2),
        "by_category": {cat: round(amt, 2) for cat, amt in rows},
    }


# ─────────────────────────────────────────────────────────────────────────
# Stock
# ─────────────────────────────────────────────────────────────────────────

def get_stock_summary(company_id: str) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    items = cdb.query(StockItem).filter_by(company_id=company_id).all()
    low_stock = [i for i in items if i.reorder_level and i.quantity <= i.reorder_level]
    total_value = sum((i.quantity or 0) * (i.purchase_rate or 0) for i in items)
    return {
        "intent": "stock_summary",
        "total_items": len(items),
        "low_stock_count": len(low_stock),
        "low_stock_items": [{"name": i.name, "qty": i.quantity, "reorder_level": i.reorder_level} for i in low_stock[:10]],
        "total_stock_value": round(total_value, 2),
    }


def get_stock_item_detail(company_id: str, identifier: str) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    ident = f"%{identifier.strip()}%"
    item = (
        cdb.query(StockItem)
        .filter(StockItem.company_id == company_id,
                 (StockItem.name.ilike(ident)) | (StockItem.code.ilike(ident)))
        .first()
    )
    if not item:
        return {"intent": "stock_item_detail", "found": False, "query": identifier}
    return {
        "intent": "stock_item_detail",
        "found": True,
        "name": item.name,
        "code": item.code,
        "category": item.category,
        "quantity": item.quantity,
        "unit": item.unit,
        "purchase_rate": item.purchase_rate,
        "selling_price": item.selling_price,
        "hsn": item.hsn,
        "gst_percent": item.gst_percent,
        "reorder_level": item.reorder_level,
    }


# ─────────────────────────────────────────────────────────────────────────
# Manifest
# ─────────────────────────────────────────────────────────────────────────

def get_manifest_summary(company_id: str, days: int = 30) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    cutoff = date.today() - timedelta(days=days)
    manifests = (
        cdb.query(CompanyManifest)
        .filter(CompanyManifest.company_id == company_id, CompanyManifest.date >= cutoff)
        .all()
    )
    pending = [m for m in manifests if m.status == "Pending"]
    total_boxes = sum(m.total_boxes or 0 for m in manifests)
    return {
        "intent": "manifest_summary",
        "period_days": days,
        "total_manifests": len(manifests),
        "pending_manifests": len(pending),
        "total_boxes": total_boxes,
    }


# ─────────────────────────────────────────────────────────────────────────
# Loans & Cheques
# ─────────────────────────────────────────────────────────────────────────

def get_loans_summary(company_id: str) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    loans = cdb.query(Loan).filter_by(company_id=company_id, status="Active").all()
    total_outstanding = sum(l.remaining_amount for l in loans)
    return {
        "intent": "loans_summary",
        "active_loans": len(loans),
        "total_outstanding": round(total_outstanding, 2),
        "loans": [{"party_name": l.party_name, "type": l.type, "remaining": round(l.remaining_amount, 2)} for l in loans],
    }


def get_cheques_summary(company_id: str) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    pending = cdb.query(Cheque).filter_by(company_id=company_id, status="Pending").all()
    received = [c for c in pending if c.direction == "received"]
    issued = [c for c in pending if c.direction == "paid"]
    return {
        "intent": "cheques_summary",
        "pending_received_count": len(received),
        "pending_received_amount": round(sum(c.amount for c in received), 2),
        "pending_issued_count": len(issued),
        "pending_issued_amount": round(sum(c.amount for c in issued), 2),
    }


# ─────────────────────────────────────────────────────────────────────────
# NEW — Net / Gross profit, bookings, void/cancelled, counts, price list,
# WhatsApp status, user counts.
# ─────────────────────────────────────────────────────────────────────────

from customer_models import PriceList, CompanyUser


def get_client_count(company_id: str) -> Dict[str, Any]:
    """Thin wrapper — reuses get_all_clients_summary's data so the count
    is never computed a second, possibly-inconsistent way."""
    return get_all_clients_summary(company_id)


def get_supplier_count(company_id: str) -> Dict[str, Any]:
    return get_all_suppliers_summary(company_id)


def get_gross_profit_summary(company_id: str, months: int = None) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)

    sales_q = cdb.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.status.notin_(['Cancelled', 'Void']),
    )
    purchase_q = cdb.query(PurchaseInvoice).filter(PurchaseInvoice.company_id == company_id)

    if months:
        cutoff = date.today() - timedelta(days=30 * months)
        sales_q = sales_q.filter(Invoice.date >= cutoff)
        purchase_q = purchase_q.filter(PurchaseInvoice.date >= cutoff)

    total_sales = sum(inv.grand_total or 0 for inv in sales_q.all())
    total_purchase = sum(p.grand_total or 0 for p in purchase_q.all())
    gross_profit = total_sales - total_purchase

    return {
        "intent": "gross_profit_summary",
        "period_months": months,
        "total_sales": round(total_sales, 2),
        "total_purchase": round(total_purchase, 2),
        "gross_profit": round(gross_profit, 2),
    }


def get_net_profit_summary(company_id: str, months: int = None) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)

    sales_q = cdb.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.status.notin_(['Cancelled', 'Void']),
    )
    purchase_q = cdb.query(PurchaseInvoice).filter(PurchaseInvoice.company_id == company_id)
    expense_q = cdb.query(Expense).filter(Expense.company_id == company_id)

    if months:
        cutoff = date.today() - timedelta(days=30 * months)
        sales_q = sales_q.filter(Invoice.date >= cutoff)
        purchase_q = purchase_q.filter(PurchaseInvoice.date >= cutoff)
        expense_q = expense_q.filter(Expense.date >= cutoff)

    total_sales = sum(inv.grand_total or 0 for inv in sales_q.all())
    total_purchase = sum(p.grand_total or 0 for p in purchase_q.all())
    total_expenses = sum(e.amount or 0 for e in expense_q.all())

    gross_profit = total_sales - total_purchase
    net_profit = gross_profit - total_expenses

    return {
        "intent": "net_profit_summary",
        "period_months": months,
        "total_sales": round(total_sales, 2),
        "total_purchase": round(total_purchase, 2),
        "total_expenses": round(total_expenses, 2),
        "gross_profit": round(gross_profit, 2),
        "net_profit": round(net_profit, 2),
        "is_profitable": net_profit >= 0,
    }


def get_bookings_list(company_id: str, days: int = 30, limit: int = 20) -> Dict[str, Any]:
    """'Booking' = a sales Invoice row (matches this file's own comment
    elsewhere: sales invoices are also called 'booking invoices'/AWB/docket).
    Excludes Cancelled/Void — see get_void_cancelled_list for those."""
    cdb = get_customer_session(company_id)
    cutoff = date.today() - timedelta(days=days)
    q = (
        cdb.query(Invoice)
        .filter(
            Invoice.company_id == company_id,
            Invoice.date >= cutoff,
            Invoice.status.notin_(['Cancelled', 'Void']),
        )
        .order_by(Invoice.date.desc())
    )
    total_count = q.count()
    rows = q.limit(limit).all()
    return {
        "intent": "bookings_list",
        "period_days": days,
        "total_bookings": total_count,
        "bookings": [
            {
                "invoice_id": inv.invoice_id,
                "date": inv.date.strftime("%d %b %Y"),
                "status": inv.status,
                "grand_total": inv.grand_total,
                "docket_no": inv.docket_no,
            }
            for inv in rows
        ],
    }


def get_void_cancelled_list(company_id: str, days: int = 30, limit: int = 20) -> Dict[str, Any]:
    cdb = get_customer_session(company_id)
    cutoff = date.today() - timedelta(days=days)
    q = (
        cdb.query(Invoice)
        .filter(
            Invoice.company_id == company_id,
            Invoice.date >= cutoff,
            Invoice.status.in_(['Cancelled', 'Void']),
        )
        .order_by(Invoice.date.desc())
    )
    total_count = q.count()
    rows = q.limit(limit).all()
    return {
        "intent": "void_cancelled_list",
        "period_days": days,
        "total_void_cancelled": total_count,
        "items": [
            {
                "invoice_id": inv.invoice_id,
                "date": inv.date.strftime("%d %b %Y"),
                "status": inv.status,
                "grand_total": inv.grand_total,
            }
            for inv in rows
        ],
    }


def get_price_list_status(company_id: str, identifier: str = None) -> Dict[str, Any]:
    """identifier, when given, filters to one courier. Without one,
    returns the most recent upload per courier."""
    cdb = get_customer_session(company_id)
    q = cdb.query(PriceList).filter(PriceList.company_id == company_id)
    if identifier:
        q = q.filter(PriceList.courier.ilike(f"%{identifier.strip()}%"))
    rows = q.order_by(PriceList.uploaded_at.desc()).all()

    if not rows:
        return {"intent": "price_list_status", "found": False, "query": identifier}

    latest_by_courier = {}
    for r in rows:
        if r.courier not in latest_by_courier:
            latest_by_courier[r.courier] = r

    return {
        "intent": "price_list_status",
        "found": True,
        "most_recent_upload": rows[0].uploaded_at.strftime("%d %b %Y %H:%M"),
        "most_recent_courier": rows[0].courier,
        "by_courier": [
            {
                "courier": r.courier,
                "list_type": r.list_type,
                "filename": r.filename,
                "uploaded_at": r.uploaded_at.strftime("%d %b %Y %H:%M"),
                "is_active": r.is_active,
            }
            for r in latest_by_courier.values()
        ],
    }


def get_whatsapp_status(company_id: str) -> Dict[str, Any]:
    """NOTE: uses the platform DB Company model, NOT get_customer_session().
    whatsapp_enabled / whatsapp_api_key live on Company in platform_models,
    not in the per-tenant erp_<company_id> database — this is the one
    function in this file that deliberately breaks the cdb convention,
    because the data itself lives outside the tenant DB."""
    from platform_models import Company
    company = Company.query.filter_by(company_id=company_id).first()
    if not company:
        return {"intent": "whatsapp_status", "found": False}
    return {
        "intent": "whatsapp_status",
        "found": True,
        "connected": bool(getattr(company, "whatsapp_enabled", False)),
        "has_api_key": bool(getattr(company, "whatsapp_api_key", None)),
    }


def get_user_count_summary(company_id: str) -> Dict[str, Any]:
    """Roles confirmed in app.py: owner, manager, employee, accountant.
    (super_admin is platform-level, not a per-company role — excluded.)"""
    cdb = get_customer_session(company_id)
    users = cdb.query(CompanyUser).filter_by(company_id=company_id).all()

    by_role = {}
    for u in users:
        role = (u.role or "employee").lower()
        by_role[role] = by_role.get(role, 0) + 1

    active_count = sum(1 for u in users if u.is_active)

    return {
        "intent": "user_count_summary",
        "total_users": len(users),
        "active_users": active_count,
        "inactive_users": len(users) - active_count,
        "by_role": by_role,
    }
