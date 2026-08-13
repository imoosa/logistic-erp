"""
whatsapp_templates.py
──────────────────────
Resolver for per-company, per-event WhatsApp template variables.

Uses the EXISTING WhatsAppTemplate model in platform_models.py — this file
does not define its own model. platform_models.WhatsAppTemplate needs two
columns added:

    header_type    VARCHAR(20) NOT NULL DEFAULT 'none'   -- none|document|image|video
    variables_json TEXT NULL                              -- ordered {{ placeholder }} list

If variables_json is NULL for a given (company_id, template_key) row — or
the row doesn't exist at all — callers should fall back to their old
hardcoded-params behavior. That's what lets you migrate companies one at a
time instead of all at once.

Placeholder syntax reuses whatsapp_connector.py's {{ dotted.path }} resolver
so there's exactly one templating mini-language in this codebase, not two.
"""

import json
from collections import OrderedDict
from whatsapp_connector import render_value


class TemplateParamMismatchError(Exception):
    """
    Raised when a template's variables_json doesn't resolve to exactly
    param_count values. Callers MUST catch this and log the .args[0]
    message to WhatsAppLog.error_message — it's meant to be read by a
    human in the campaign/send-log screen, not just printed to console.
    """
    pass


# ─── FIELD CATALOGUE ────────────────────────────────────────────────────────
# Single source of truth for "what data can a template variable point at."
# The admin config form (app.py route + admin_whatsapp_templates.html) builds
# its dropdowns from this. resolve_params() below uses the exact same
# placeholder strings. If you add a new field, add it HERE ONLY — both the
# UI and the resolver pick it up automatically.
#
# Key = value stored in the <select>, sent back on form submit.
# Value = (display label, {{ placeholder }} string used against build_ctx()).
#
# "common" fields apply to every event. Event-specific fields only make
# sense for that one event (e.g. carrier/carrier_ref only exist on the
# carrier_ref_updated send) and are listed separately so the form doesn't
# offer nonsense options like "Carrier Name" on a booking-confirmation template.

COMMON_FIELDS = OrderedDict([
    ("docket_no",         ("Docket / AWB Number",   "{{ invoice.docket_no }}")),
    ("invoice_date",      ("Invoice Date",           "{{ invoice.date }}")),
    ("destination",       ("Destination",            "{{ invoice.destination }}")),
    ("expected_delivery", ("Expected Delivery Date", "{{ invoice.expected_delivery }}")),
    ("shipment_status",   ("Shipment Status",        "{{ invoice.status }}")),
    ("client_name",       ("Client / Customer Name", "{{ client.name }}")),
    ("client_phone",      ("Client Phone",           "{{ client.phone }}")),
    ("company_name",      ("Company Name",           "{{ company.name }}")),
    ("company_phone",     ("Company Phone",          "{{ company.phone }}")),
])

EVENT_SPECIFIC_FIELDS = {
    "carrier_ref_updated": OrderedDict([
        ("carrier_name", ("Carrier Name",      "{{ carrier.name }}")),
        ("carrier_ref",  ("Carrier Reference", "{{ carrier.ref }}")),
    ]),
}

EVENT_DEFS = [
    ("invoice_created",    "Booking Confirmation", "Sent when an invoice/shipment is first generated"),
    ("invoice_updated",    "Shipment Update",      "Sent when an existing invoice is edited/updated"),
    ("carrier_ref_updated","Carrier Reference Update", "Sent when a carrier reference number is added/changed"),
]


def field_options_for_event(event_key):
    """Ordered dict of {field_key: (label, placeholder)} valid for this event."""
    opts = OrderedDict(COMMON_FIELDS)
    opts.update(EVENT_SPECIFIC_FIELDS.get(event_key, {}))
    return opts


def placeholder_for_field(event_key, field_key):
    opts = field_options_for_event(event_key)
    if field_key not in opts:
        raise TemplateParamMismatchError(
            f"'{field_key}' is not a valid field for event '{event_key}'."
        )
    return opts[field_key][1]


def build_ctx(invoice=None, client=None, company=None, meta=None, extra=None):
    """
    Build the resolution context passed to render_value() for a given send.
    Safe to call with any argument as None — you get empty strings back
    instead of an AttributeError.
    """
    meta = meta or {}
    extra = extra or {}

    ctx = {
        "invoice": {
            "docket_no": meta.get("docket_no", invoice.invoice_id if invoice else ""),
            "date": invoice.date.strftime("%d-%b-%Y") if invoice and invoice.date else "",
            "destination": meta.get("destination", ""),
            "expected_delivery": meta.get("expected_delivery", ""),
            "status": getattr(invoice, "status", "") or "",
        },
        "client": {
            "name": (client.name if client else None) or "Customer",
            "phone": (client.phone if client else "") or "",
        },
        "company": {
            "phone": (company.phone if company else "") or "",
            "name": (company.company_name if company else "") or "",
        },
    }
    # Event-specific extras (e.g. carrier/carrier_ref for carrier_ref_updated)
    # get merged in by the caller so this stays generic across all events.
    ctx.update(extra)
    return ctx


def resolve_params(tpl, ctx):
    """
    tpl: a WhatsAppTemplate row (must have variables_json populated)
    ctx: dict built by build_ctx()

    Returns an ordered list of strings, one per {{N}} slot in the approved
    template — length is whatever variables_json says, not a fixed number.
    """
    var_list = json.loads(tpl.variables_json)

    if tpl.param_count and len(var_list) != tpl.param_count:
        raise TemplateParamMismatchError(
            f"Template '{tpl.template_key}' for company '{tpl.company_id}' is "
            f"misconfigured: param_count={tpl.param_count} but variables_json "
            f"has {len(var_list)} entries. Message NOT sent — fix the template "
            f"config (WhatsApp Settings) before retrying."
        )

    resolved = []
    unresolved = []
    for placeholder in var_list:
        try:
            value = render_value(placeholder, ctx)
        except Exception as e:
            unresolved.append(f"{placeholder} ({e})")
            value = ""
        resolved.append(str(value))

    if unresolved:
        raise TemplateParamMismatchError(
            f"Template '{tpl.template_key}' for company '{tpl.company_id}' "
            f"references field(s) that couldn't be resolved: {'; '.join(unresolved)}. "
            f"Message NOT sent — check variables_json against available invoice/"
            f"client/company fields."
        )

    return resolved


def get_template_config(company_id, event_key):
    """
    Looks up the configured template for this company/event from the
    EXISTING WhatsAppTemplate table (platform_models.py).

    Returns None if:
      - no row exists for this (company_id, template_key), or
      - the row exists but variables_json is unset (company not migrated
        to dynamic params yet)

    Callers should fall back to their old hardcoded-params behavior in
    either case.
    """
    from platform_models import WhatsAppTemplate

    tpl = WhatsAppTemplate.query.filter_by(
        company_id=company_id, template_key=event_key, is_active=True
    ).first()

    if not tpl or not tpl.variables_json:
        return None

    return tpl
