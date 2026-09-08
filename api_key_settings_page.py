# ─────────────────────────────────────────────────────────────────────────
# ADD TO app.py — self-service API key management for logged-in company
# users. One route, inline template, no separate .html file needed.
# Depends on CompanyApiKey + generate_api_key from platform_models
# (see api_tracking_patch.py from earlier in this conversation).
# ─────────────────────────────────────────────────────────────────────────
from platform_models import CompanyApiKey, generate_api_key
from flask import render_template_string

API_KEY_PAGE_TEMPLATE = """
{% extends "base.html" %}
{% block content %}
<h2>API Access — Track Shipments on Your Website</h2>
<p>Generate a key, give it to whoever manages your website, and they can
show live tracking on your own site using your own database.</p>

{% if new_key %}
  <div style="border:2px solid #c00;padding:1em;margin-bottom:1.5em;">
    <strong>Copy this key now — it will not be shown again:</strong>
    <pre style="background:#f4f4f4;padding:0.5em;user-select:all;">{{ new_key }}</pre>

    <p>Give these two things to your website developer:</p>
    <ol>
      <li>This key</li>
      <li>This snippet — it goes in <code>wp-config.php</code> if WordPress,
          or wherever their backend keeps secrets:</li>
    </ol>
    <pre style="background:#f4f4f4;padding:0.5em;">define( 'MAGNUSTIC_API_KEY', '{{ new_key }}' );</pre>
    <p>Full WordPress plugin file (shortcode <code>[track_shipment]</code>) is
       available from your account manager — ask for
       <code>magnustic-tracking.php</code>.</p>
  </div>
{% endif %}

<h3>Generate a new key</h3>
<form method="post">
  <label>Label (so you recognize it later — e.g. "Main website")</label><br>
  <input type="text" name="label" placeholder="Main website" maxlength="100"><br><br>
  <button type="submit">Generate API Key</button>
</form>

<h3>Existing keys</h3>
{% if keys %}
<table border="1" cellpadding="6" style="border-collapse:collapse;">
  <tr><th>Label</th><th>Key (prefix only)</th><th>Created</th><th>Last used</th><th>Status</th><th></th></tr>
  {% for k in keys %}
  <tr>
    <td>{{ k.label or "—" }}</td>
    <td><code>{{ k.key_prefix }}...</code></td>
    <td>{{ k.created_at.strftime("%d %b %Y") }}</td>
    <td>{{ k.last_used_at.strftime("%d %b %Y %H:%M") if k.last_used_at else "Never used" }}</td>
    <td>{{ "Active" if k.is_active else "Revoked" }}</td>
    <td>
      {% if k.is_active %}
      <form method="post" action="{{ url_for('revoke_api_key', key_id=k.id) }}"
            onsubmit="return confirm('Revoke this key? Anything using it will stop working immediately.');">
        <button type="submit">Revoke</button>
      </form>
      {% endif %}
    </td>
  </tr>
  {% endfor %}
</table>
{% else %}
<p>No keys yet.</p>
{% endif %}
{% endblock %}
"""


@app.route("/settings/api-keys", methods=["GET", "POST"])
@login_required
def manage_api_keys():
    company_id = session.get("company_id")
    new_key = None

    if request.method == "POST":
        label = request.form.get("label", "").strip() or None
        new_key, _row = generate_api_key(company_id, label=label)
        flash("New API key generated — copy it now, it won't be shown again.")

    keys = (CompanyApiKey.query
            .filter_by(company_id=company_id)
            .order_by(CompanyApiKey.created_at.desc())
            .all())

    return render_template_string(API_KEY_PAGE_TEMPLATE, keys=keys, new_key=new_key)


@app.route("/settings/api-keys/<int:key_id>/revoke", methods=["POST"])
@login_required
def revoke_api_key(key_id):
    company_id = session.get("company_id")
    row = CompanyApiKey.query.filter_by(id=key_id, company_id=company_id).first()
    if not row:
        abort(404)
    row.is_active = False
    db.session.commit()
    flash(f"Revoked key {row.key_prefix}...")
    return redirect(url_for("manage_api_keys"))

# ─────────────────────────────────────────────────────────────────────────
# WHAT THIS DELIBERATELY LEAVES OUT:
#
# 1. No per-key usage cap or dashboard ("N calls this month"). If you want
#    that later, add a hit-counter column and increment it in require_api_key
#    (from api_tracking_patch.py) alongside last_used_at.
#
# 2. No max-keys-per-company limit. Fine at your current tenant count; add
#    a check in manage_api_keys() if someone starts generating dozens.
#
# 3. This page trusts @login_required the same way your other internal
#    routes do — whoever's logged into that company session can see/revoke
#    keys. If you have role separation (staff vs. company-owner) elsewhere
#    in the app, decide whether key management needs the tighter role too.
# ─────────────────────────────────────────────────────────────────────────
