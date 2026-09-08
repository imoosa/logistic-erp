"""
permissions.py
──────────────
Per-company, per-role access control for the two non-owner roles:
'employee' (sales), 'accountant', and 'manager'.

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
from customer_models import CompanyUser, CompanyRolePermission

# Modules governed by this matrix. (company_settings / whatsapp_connect /
# employees are intentionally excluded — see module docstring.)
MODULES = [
    "dashboard", "analytics", "clients", "suppliers", "estimates", 
    "stock", "pricelist", "manifest", "invoices", "purchase",
    "creditors", "debtors", "expenses", "cash", "bank", "cheques",
    "loans", "receipts_payments", "backup", "customer_invoices",
]

ACTIONS = ["view", "create", "edit", "delete"]

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
    "creditors":         "Creditors",
    "debtors":           "Debtors",
    "expenses":          "Expenses",
    "cash":              "Cash in Hand",
    "bank":              "Bank Accounts",
    "cheques":           "Cheque Register",
    "loans":             "Loan Accounts",
    "receipts_payments": "Receipts & Payments",
    "backup":            "Backup",
    "customer_invoices": "Customer Invoices",
}


def _none(modules):
    return {m: {a: False for a in ACTIONS} for m in modules}


def _all(modules):
    # NOTE: "delete" is deliberately excluded from the bulk grant. Nobody —
    # not even manager — gets delete by default. The only way delete=True
    # ever appears for a non-owner role is an explicit per-employee owner
    # override (see get_effective_permissions / CompanyUser.permission_overrides).
    return {m: {a: (True if a != "delete" else False) for a in ACTIONS} for m in modules}


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
        "customer_invoices": {"view": True, "create": True, "edit": True},
    },
    "accountant": {
        **_all(MODULES),
        "dashboard": {"view": False, "create": False, "edit": False},
        "analytics": {"view": False, "create": False, "edit": False},
        "customer_invoices": {"view": True, "create": True, "edit": True},
    },
    "manager": {
        **_all(MODULES),
        "customer_invoices": {"view": True, "create": True, "edit": True},
    },
}

# The per-module override dicts above (e.g. "clients": {"view": True, ...})
# only specify the actions that differ from _none()'s baseline, so they don't
# carry a "delete" key. Normalize every module/action combination to be
# present and explicitly False unless an owner has granted it, so downstream
# code (templates, _merge) never has to guess about a missing key — and so
# "delete" can never accidentally end up True by omission.
for _role, _modules in DEFAULT_ROLE_PERMISSIONS.items():
    for _m in MODULES:
        _entry = _modules.setdefault(_m, {})
        for _a in ACTIONS:
            _entry.setdefault(_a, False)
del _role, _modules, _m, _entry, _a


# NEW: Field-level permissions for invoices
INVOICE_FIELDS = {
    # Core invoice fields
    "invoice_basic": {
        "label": "Basic Invoice Info",
        "fields": ["invoice_date", "status", "notes"],
        "default": {"view": True, "edit": False}
    },
    "invoice_customer": {
        "label": "Customer / Shipper Details",
        "fields": ["shipper_name", "shipper_contact_name", "customer_phone"],
        "default": {"view": True, "edit": False}
    },
    "invoice_sender": {
        "label": "Sender Address & ID",
        "fields": [
            "shipper_address1", "shipper_address2", "shipper_city", 
            "shipper_state", "shipper_pincode", "shipper_country",
            "shipper_doc_type", "shipper_doc_no", "client_code"
        ],
        "default": {"view": True, "edit": False}
    },
    "invoice_receiver": {
        "label": "Receiver / Consignee Details",
        "fields": [
            "receiver_name", "receiver_company", "receiver_phone",
            "receiver_address1", "receiver_address2", "receiver_city",
            "receiver_state", "receiver_pincode", "receiver_country",
            "receiver_doc_type", "receiver_doc_no"
        ],
        "default": {"view": True, "edit": False}
    },
    "invoice_service_courier": {
        "label": "Courier Company & Service",
        "fields": [
            "destination", "shipment_type", "mode", "vendor",
            "courier_company_id", "carrier", "origin", "pickup_date",
            "departure_time", "expected_delivery", "comments"
        ],
        "default": {"view": True, "edit": False}
    },
    "invoice_service_tracking": {
        "label": "Reference No. & Tracking No.",
        "fields": ["tracking_number", "carrier_ref"],
        "default": {"view": True, "edit": False}
    },
    "invoice_packages": {
        "label": "Packages / Items",
        "fields": [
            "pkg_name", "pkg_type", "pkg_qty", "pkg_l", "pkg_w", 
            "pkg_h", "pkg_weight", "pkg_rate", "pkg_discount",
            "pkg_discwt", "pkg_volwt", "pkg_chgwt"
        ],
        "default": {"view": True, "edit": False}
    },
    "invoice_packages_actual_weight": {
        "label": "Packages - Actual Weight",
        "fields": ["pkg_weight"],
        "default": {"view": True, "edit": False}
    },
    "invoice_charges": {
        "label": "Freight & Charges",
        "fields": [
            "freight_amount", "freight_weight", "freight_rate_per_kg",
            "fuel_surcharge", "other_charges", "discount_amount",
            "other_charges_reason"
        ],
        "default": {"view": True, "edit": False}
    },
    "invoice_performa": {
        "label": "Performa Invoice Items",
        "fields": [
            "perf_desc", "perf_box", "perf_hsn", "perf_unit",
            "perf_weight_item", "perf_qty", "perf_rate",
            "perf_weight", "perf_reference"
        ],
        "default": {"view": True, "edit": False}
    },
    "invoice_resale": {
        "label": "Resale / Return Charges",
        "fields": ["resale_amount", "resale_reason", "resale_date", "resale_notes"],
        "default": {"view": True, "edit": False}
    }
}

# ── Hard-locked fields (never editable by certain roles) ─────────────────────
HARD_LOCKED_EDIT = {
    "employee": set(),
    "accountant": set(),
    "manager": set(),
}

# Default field permissions for each role
DEFAULT_FIELD_PERMISSIONS = {
    "employee": {
        # Basic view-only access - NO EDIT by default
        "invoice_basic": {"view": True, "edit": False},
        "invoice_customer": {"view": True, "edit": False},
        "invoice_sender": {"view": True, "edit": False},
        "invoice_receiver": {"view": True, "edit": False},
        "invoice_service_courier": {"view": True, "edit": False},
        "invoice_service_tracking": {"view": True, "edit": False},
        "invoice_packages": {"view": True, "edit": False},
        "invoice_packages_actual_weight": {"view": True, "edit": False},
        "invoice_charges": {"view": True, "edit": False},
        "invoice_performa": {"view": True, "edit": False},
        "invoice_resale": {"view": True, "edit": False},
    },
    "manager": {
        # Manager has full access by default
        "invoice_basic": {"view": True, "edit": True},
        "invoice_customer": {"view": True, "edit": True},
        "invoice_sender": {"view": True, "edit": True},
        "invoice_receiver": {"view": True, "edit": True},
        "invoice_service_courier": {"view": True, "edit": True},
        "invoice_service_tracking": {"view": True, "edit": True},
        "invoice_packages": {"view": True, "edit": True},
        "invoice_packages_actual_weight": {"view": True, "edit": False},
        "invoice_charges": {"view": True, "edit": True},
        "invoice_performa": {"view": True, "edit": True},
        "invoice_resale": {"view": True, "edit": True},
    },
    "accountant": {
        # Accountant can edit financial fields only
        "invoice_basic": {"view": True, "edit": True},
        "invoice_customer": {"view": True, "edit": False},
        "invoice_sender": {"view": True, "edit": False},
        "invoice_receiver": {"view": True, "edit": False},
        "invoice_service_courier": {"view": True, "edit": False},
        "invoice_service_tracking": {"view": True, "edit": False},
        "invoice_packages": {"view": True, "edit": False},
        "invoice_packages_actual_weight": {"view": True, "edit": False},
        "invoice_charges": {"view": True, "edit": True},
        "invoice_performa": {"view": True, "edit": False},
        "invoice_resale": {"view": True, "edit": False},
    }
}


def get_field_permissions(role, user_id=None, company_id=None, cdb=None):
    """
    Get field-level permissions for a user.
    Returns a dict: {field_group: {"view": bool, "edit": bool}}
    """
    # Owners and super_admin have full access
    if role in ("owner", "super_admin"):
        return {key: {"view": True, "edit": True} for key in INVOICE_FIELDS}
    
    # Base: the role's built-in default, for every field group. Overrides
    # below are merged group-by-group on top of this — never returned
    # wholesale — so a partial save (e.g. only "invoice_charges" changed)
    # can't silently wipe access to every other field group. That silent
    # wipe was the "field access not working" bug: a role-level or
    # per-user override JSON that only contained some field groups caused
    # every *other* group to read as {} -> view=False, edit=False.
    import copy
    result = copy.deepcopy(DEFAULT_FIELD_PERMISSIONS.get(role, DEFAULT_FIELD_PERMISSIONS["employee"]))

    # Layer 2: company-wide role override, if set.
    if company_id and cdb:
        role_perm = cdb.query(CompanyRolePermission).filter_by(
            company_id=company_id, role=role
        ).first()
        if role_perm and role_perm.field_permissions_json:
            try:
                for group, perm in json.loads(role_perm.field_permissions_json).items():
                    if group in result and isinstance(perm, dict):
                        result[group].update(perm)
            except (ValueError, TypeError):
                pass

    # Layer 3: per-employee override, if set — wins over the role override.
    if user_id and company_id and cdb:
        user = cdb.query(CompanyUser).filter_by(
            company_id=company_id, user_id=user_id
        ).first()
        if user and user.field_permissions:
            try:
                for group, perm in json.loads(user.field_permissions).items():
                    if group in result and isinstance(perm, dict):
                        result[group].update(perm)
            except (ValueError, TypeError):
                pass

    # Hard-locked fields can never be re-opened by an override, at any layer.
    for locked_group in HARD_LOCKED_EDIT.get(role, ()):
        if locked_group in result:
            result[locked_group]["edit"] = False

    return result


def can_edit_field(role, field_group, user_id=None, company_id=None, cdb=None):
    """Check if user can edit a specific field group"""
    perms = get_field_permissions(role, user_id, company_id, cdb)
    return perms.get(field_group, {}).get("edit", False)


def can_view_field(role, field_group, user_id=None, company_id=None, cdb=None):
    """Check if user can view a specific field group"""
    perms = get_field_permissions(role, user_id, company_id, cdb)
    return perms.get(field_group, {}).get("view", False)

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