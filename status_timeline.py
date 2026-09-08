# ─────────────────────────────────────────────────────────────────────────
# ADD TO app.py — replaces the "instant redirect" version from earlier.
# The customer now sees an in-app status page; the carrier link only
# appears once the shipment has actually left the building.
# ─────────────────────────────────────────────────────────────────────────
from customer_models import Invoice, ManifestEntry


def get_shipment_status(cdb, docket_no: str):
    """
    Returns an ordered list of stage dicts for the timeline UI, plus the
    carrier redirect URL (or None if not dispatched yet).
    Returns None if the docket number doesn't exist at all in this company's DB.
    """
    invoice = cdb.query(Invoice).filter_by(docket_no=docket_no).first()
    if not invoice:
        return None

    entry = cdb.query(ManifestEntry).filter_by(docket_no=docket_no).first()

    stages = [
        {"label": "Booked", "done": True, "at": invoice.created_at},
        {"label": "Ready for Dispatch", "done": bool(entry and entry.generated_at),
         "at": entry.generated_at if entry else None},
        {"label": f"In Transit to {entry.courier_name}" if entry and entry.courier_name else "In Transit",
         "done": bool(entry and entry.dispatched_at),
         "at": entry.dispatched_at if entry else None},
    ]

    carrier_redirect_url = None
    if entry and entry.dispatched_at and entry.courier_name:
        carrier_key = normalize_carrier(entry.courier_name)
        cfg = CarrierTrackingConfig.query.filter_by(carrier_key=carrier_key, is_active=True).first()
        if cfg:
            carrier_redirect_url = cfg.tracking_url_template.replace("{tracking_number}", docket_no)

    return {
        "docket_no": docket_no,
        "courier_name": entry.courier_name if entry else None,
        "stages": stages,
        "carrier_redirect_url": carrier_redirect_url,
    }


def _lookup_status(company_id: str, docket_no: str):
    cdb = get_customer_session(company_id)
    return get_shipment_status(cdb, docket_no)


# ── 1. Branded per-company page ─────────────────────────────────────────────
@app.route("/track/<company_slug>", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def public_tracking(company_slug):
    company = Company.query.filter_by(public_slug=company_slug).first_or_404()
    status = None
    error = None
    if request.method == "POST":
        docket_no = request.form.get("docket_no", "").strip()
        status = _lookup_status(company.company_id, docket_no)
        if not status:
            error = "No shipment found for that tracking number."
    return render_template("tracking_status.html", company=company, status=status, error=error)


# ── 2. Magic link from the WhatsApp message — direct hit, no form ──────────
@app.route("/t/<company_id>/<docket_no>")
@limiter.limit("30 per minute")
def track_magic_link(company_id, docket_no):
    status = _lookup_status(company_id, docket_no)
    if not status:
        abort(404)
    company = Company.query.filter_by(company_id=company_id).first()
    return render_template("tracking_status.html", company=company, status=status, error=None)


# ── 3. Unbranded fallback — needs TrackingIndex to find the company first ──
@app.route("/track", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def public_tracking_generic():
    status = None
    error = None
    if request.method == "POST":
        docket_no = request.form.get("docket_no", "").strip()
        idx = TrackingIndex.query.filter_by(docket_no=docket_no).first()
        if not idx:
            error = "No shipment found for that tracking number."
        else:
            status = _lookup_status(idx.company_id, docket_no)
    return render_template("tracking_status.html", company=None, status=status, error=error)


# ─────────────────────────────────────────────────────────────────────────
# Note on the "Ready for Dispatch" stage timing out: nothing here handles
# what the customer sees if a shipment sits in "Booked" for three days
# because staff forgot to run the manifest. That's not a code gap — that's
# an ops process question for you to decide, not something a status page
# can paper over.
# ─────────────────────────────────────────────────────────────────────────
