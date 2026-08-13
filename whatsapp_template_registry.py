"""
whatsapp_template_registry.py
──────────────────────────────
Fixed, hand-maintained catalogue of approved WhatsApp templates — 2-3
options per event. No database table, no per-company variable-mapping
admin form. A company just picks one option (by key) in WhatsApp Settings,
and the exact right number/order of params gets built automatically.

To add a new option:
  1. Get the template approved in your WhatsApp provider's dashboard first.
  2. Note the EXACT template name (what gets sent to the API) and the
     EXACT order of variables it was approved with.
  3. Add an entry below. Nothing else in the codebase needs to change.

IMPORTANT: "template_name" below must match the exact approved name in
Meta/your provider's dashboard — that's what actually gets sent in the API
payload. The dict key (e.g. "booking_basic") is just an internal label for
the dropdown in Settings; it never goes over the wire.
"""


def _fmt_date(d):
    return d.strftime("%d-%b-%Y") if d else ""


def _docket(ctx):
    return ctx["meta"].get("docket_no", ctx["invoice"].invoice_id)


def _client_name(ctx):
    client = ctx.get("client")
    return (client.name if client else None) or "Customer"


# ── Booking confirmation (fires on invoice generate) ────────────────────────
INVOICE_CREATED_OPTIONS = {
    "booking_basic": {
        "template_name": "booking",   # ⚠️ CONFIRM this matches your approved name
        "label": "Basic — Docket, Date, Company Phone (3 vars)",
        "build_params": lambda ctx: [
            _docket(ctx),
            _fmt_date(ctx["invoice"].date),
            ctx["company"].phone or "",
        ],
    },
    "booking_4var": {
        "template_name": "booking",   # ⚠️ FILL IN once you confirm var #4 below
        "label": "With 4th variable — TODO, fill in once confirmed (4 vars)",
        "build_params": lambda ctx: [
            _docket(ctx),
            _fmt_date(ctx["invoice"].date),
            ctx["company"].phone or "",
            # ⚠️ PLACEHOLDER — replace with whatever var #4 actually is,
            # e.g. _client_name(ctx), or ctx["meta"].get("destination", ""),
            "",
        ],
    },
}

# ── Shipment status update (fires on invoice edit) ──────────────────────────
INVOICE_UPDATED_OPTIONS = {
    "shipment_update_basic": {
        "template_name": "shipment_update",
        "label": "Basic — Docket, Status, Date (3 vars)",
        "build_params": lambda ctx: [
            _docket(ctx),
            getattr(ctx["invoice"], "status", "") or "Updated",
            _fmt_date(ctx["invoice"].date),
        ],
    },
    "shipment_update_with_client": {
        "template_name": "shipment_update_v2",
        "label": "With Client Name — Docket, Status, Date, Client Name (4 vars)",
        "build_params": lambda ctx: [
            _docket(ctx),
            getattr(ctx["invoice"], "status", "") or "Updated",
            _fmt_date(ctx["invoice"].date),
            _client_name(ctx),
        ],
    },
}

# ── Carrier reference updated ────────────────────────────────────────────────
CARRIER_REF_UPDATED_OPTIONS = {
    "carrier_update_basic": {
        "template_name": "carrier_reference_update",
        "label": "Basic — Client, Docket, Carrier Ref, Carrier (4 vars)",
        "build_params": lambda ctx: [
            _client_name(ctx),
            _docket(ctx),
            ctx["extra"].get("carrier_ref", ""),
            ctx["extra"].get("carrier", ""),
        ],
    },
    "carrier_update_full": {
        "template_name": "carrier_reference_update_full",
        "label": "Full — + Destination, Expected Delivery (6 vars)",
        "build_params": lambda ctx: [
            _client_name(ctx),
            _docket(ctx),
            ctx["extra"].get("carrier_ref", ""),
            ctx["extra"].get("carrier", ""),
            ctx["meta"].get("destination", ""),
            ctx["meta"].get("expected_delivery", ""),
        ],
    },
}

EVENT_OPTIONS = {
    "invoice_created": INVOICE_CREATED_OPTIONS,
    "invoice_updated": INVOICE_UPDATED_OPTIONS,
    "carrier_ref_updated": CARRIER_REF_UPDATED_OPTIONS,
}


def get_option(event_key, option_key):
    """Returns the option dict, or None if not found."""
    return EVENT_OPTIONS.get(event_key, {}).get(option_key)


def build_send_args(event_key, option_key, ctx):
    """
    Returns (template_name, params) for this event/option, or (None, None)
    if the option_key isn't registered — callers must treat that as a hard
    rejection, not silently fall back to a guessed param count.
    """
    option = get_option(event_key, option_key)
    if not option:
        return None, None
    return option["template_name"], option["build_params"](ctx)
