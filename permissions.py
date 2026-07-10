"""
permissions.py
──────────────
Per-company, per-role access control for the two non-owner roles:
'employee' (sales) and 'accountant'.

Scope, deliberately:
- Three actions only: view, create, edit. NO delete anywhere in this
  system — that was an explicit decision, not an oversight. Every delete
  route in app.py is untouched and still governed only by owner_required
  / login_required as before.
- 'owner' and 'super_admin' always have full access and never touch this
  matrix.
- company_settings, whatsapp_connect, and employees/user-management stay
  behind the existing @owner_required decorator — they are intentionally
  NOT part of this override system, so an owner can never accidentally
  (or an accountant never can) grant access to them via the settings UI.

Resolution order for a given (company, role, module, action):
  1. Per-user override on CompanyUser.permission_overrides (if the key
     is present there, it wins — full stop).
  2. Per-company override on CompanyRolePermission for that role.
  3. Built-in DEFAULT_ROLE_PERMISSIONS below.
"""

import json

# Modules governed by this matrix. (company_settings / whatsapp_connect /
# employees are intentionally excluded — see module docstring.)
MODULES = [
    "dashboard", "analytics", "clients", "suppliers", "estimates",
    "stock", "pricelist", "manifest", "invoices", "purchase", "orders",
    "expenses", "cash", "bank", "cheques", "loans", "receipts_payments",
    "backup",
]

ACTIONS = ["view", "create", "edit"]

# Human-readable labels for the settings UI matrix.
MODULE_LABELS = {
    "dashboard":         "Dashboard",
    "analytics":         "Analytics / Reports",
    "clients":           "Clients",
    "suppliers":         "Suppliers",
    "estimates":         "Proforma Invoice (Estimates)",
    "stock":             "Stock / Inventory",
    "pricelist":         "Price List",
    "manifest":          "Manifest",
    "invoices":          "Booking Invoice",
    "purchase":          "Purchase Invoice",
    "orders":            "Orders",
    "expenses":          "Expenses",
    "cash":              "Cash in Hand",
    "bank":              "Bank Accounts",
    "cheques":           "Cheque Register",
    "loans":             "Loan Accounts",
    "receipts_payments": "Receipts & Payments",
    "backup":            "Backup",
}


def _none(modules):
    return {m: {a: False for a in ACTIONS} for m in modules}


def _all(modules):
    return {m: {a: True for a in ACTIONS} for m in modules}


# ── Built-in defaults ─────────────────────────────────────────────────────────
DEFAULT_ROLE_PERMISSIONS = {
    "employee": {
        **_none(MODULES),
        "clients":   {"view": True, "create": False, "edit": False},
        "suppliers": {"view": True, "create": False, "edit": False},
        "estimates": {"view": True, "create": False, "edit": False},
        "stock":     {"view": True, "create": False, "edit": False},
        "pricelist": {"view": True, "create": False, "edit": False},
        "manifest":  {"view": True, "create": False, "edit": False},
        "invoices":  {"view": True, "create": True,  "edit": False},
    },
    "accountant": {
        **_all(MODULES),
        "dashboard": {"view": False, "create": False, "edit": False},
        "analytics": {"view": False, "create": False, "edit": False},
    },
}
# 'manager' pre-dates this permission system and has no spec of its own —
# treated as an alias of 'accountant' (broad access, owner-overridable)
# rather than silently dropping existing manager users to zero access.
DEFAULT_ROLE_PERMISSIONS["manager"] = DEFAULT_ROLE_PERMISSIONS["accountant"]


def default_permissions_for(role):
    import copy
    return copy.deepcopy(DEFAULT_ROLE_PERMISSIONS.get(
        role, {m: {a: False for a in ACTIONS} for m in MODULES}
    ))


def _merge(base, override_json):
    """Merge a JSON override blob into base, module-by-module, action-by-action."""
    if not override_json:
        return base
    try:
        override = json.loads(override_json)
    except (ValueError, TypeError):
        return base
    for module, acts in override.items():
        if module not in base:
            continue
        for action, allowed in (acts or {}).items():
            if action in ACTIONS:
                base[module][action] = bool(allowed)
    return base


def get_effective_permissions(role, company_id, user_id, cdb, CompanyRolePermission, CompanyUser):
    """
    Compute the effective view/create/edit matrix for a non-owner user.
    `cdb` is the customer-db session for this company (from get_customer_session).
    """
    perms = default_permissions_for(role)

    company_row = (
        cdb.query(CompanyRolePermission)
        .filter_by(company_id=company_id, role=role)
        .first()
    )
    if company_row:
        perms = _merge(perms, company_row.permissions_json)

    user_row = (
        cdb.query(CompanyUser)
        .filter_by(user_id=user_id, company_id=company_id)
        .first()
    )
    if user_row:
        perms = _merge(perms, user_row.permission_overrides)

    return perms
