"""
AssetPro Rules Engine
Deterministic replacement/action recommendations.
Zero AI involvement — 100% reliable output.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any


# ── Thresholds (tune per business) ────────────────────────────────────────────
REPLACE_AGE_YEARS       = 8
REPLACE_MAINT_COST_PCT  = 0.30   # maintenance cost > 30% of purchase cost
POOR_CONDITIONS         = {"poor", "damaged", "critical"}
CRITICAL_CONDITIONS     = {"critical", "damaged"}
WARRANTY_WARN_DAYS      = 30
INSURANCE_WARN_DAYS     = 30
SERVICE_OVERDUE_DAYS    = 0      # any day past due = overdue
HIGH_VALUE_THRESHOLD    = 50_000
HEAVY_REPAIR_THRESHOLD  = 0.20   # 20% of purchase cost in last 12 months = "heavy repair"
IDLE_STATUSES           = {"inactive", "idle", "retired"}


# ── Core evaluator ────────────────────────────────────────────────────────────

def evaluate_asset(item, service_logs=None, fuel_logs=None) -> Dict[str, Any]:
    """
    Run all rules against a single InventoryItem.
    Returns a dict with flags, recommendations, and urgency score.
    """
    today       = datetime.utcnow().date()
    now         = datetime.utcnow()
    flags       = []
    recommend   = []
    urgency     = 0  # higher = more attention needed

    purchase_cost = float(item.purchase_cost or 0)

    # ── Age ────────────────────────────────────────────────────────────────────
    age_years = 0.0
    if item.purchase_date:
        age_years = (now - item.purchase_date).days / 365.25

    if age_years >= REPLACE_AGE_YEARS:
        flags.append({"rule": "age_limit", "detail": f"Asset is {age_years:.1f} years old (limit: {REPLACE_AGE_YEARS})"})
        urgency += 30
        recommend.append("Consider replacement — asset has exceeded service age limit.")

    # ── Condition ──────────────────────────────────────────────────────────────
    condition = (item.condition or "").lower()
    if condition in CRITICAL_CONDITIONS:
        flags.append({"rule": "critical_condition", "detail": f"Condition: {item.condition}"})
        urgency += 40
        recommend.append("Immediate inspection required — asset is in critical condition.")
    elif condition in POOR_CONDITIONS:
        flags.append({"rule": "poor_condition", "detail": f"Condition: {item.condition}"})
        urgency += 20
        recommend.append("Schedule maintenance — condition is poor.")

    # ── Maintenance cost ratio ─────────────────────────────────────────────────
    if service_logs and purchase_cost > 0:
        last_12m = now - timedelta(days=365)
        repair_cost = sum(
            float(s.cost or 0) for s in service_logs
            if s.service_date and s.service_date >= last_12m
        )
        ratio = repair_cost / purchase_cost
        if ratio >= REPLACE_MAINT_COST_PCT:
            flags.append({
                "rule": "high_repair_cost",
                "detail": f"Repair cost ₹{repair_cost:,.0f} = {ratio*100:.0f}% of purchase value"
            })
            urgency += 35
            recommend.append(
                f"Repair cost is {ratio*100:.0f}% of asset value — replacing may be cheaper."
            )

    # ── Warranty ───────────────────────────────────────────────────────────────
    if item.warranty_expiry:
        days_left = (item.warranty_expiry - today).days
        if days_left < 0:
            flags.append({"rule": "warranty_expired", "detail": f"Expired {abs(days_left)} days ago"})
            urgency += 10
        elif days_left <= WARRANTY_WARN_DAYS:
            flags.append({"rule": "warranty_expiring", "detail": f"{days_left} days remaining"})
            urgency += 15
            recommend.append(f"Warranty expires in {days_left} days — raise claims before expiry.")

    # ── Insurance ──────────────────────────────────────────────────────────────
    if item.insurance_expiry:
        days_left = (item.insurance_expiry - today).days
        if days_left < 0:
            flags.append({"rule": "insurance_expired", "detail": f"Expired {abs(days_left)} days ago"})
            urgency += 25
            recommend.append("Insurance has expired — renew immediately.")
        elif days_left <= INSURANCE_WARN_DAYS:
            flags.append({"rule": "insurance_expiring", "detail": f"{days_left} days remaining"})
            urgency += 20
            recommend.append(f"Insurance expires in {days_left} days — initiate renewal.")

    # ── Service overdue ────────────────────────────────────────────────────────
    if item.next_service_due:
        days_left = (item.next_service_due - today).days
        if days_left < SERVICE_OVERDUE_DAYS:
            flags.append({"rule": "service_overdue", "detail": f"Overdue by {abs(days_left)} days"})
            urgency += 20
            recommend.append(f"Service is overdue by {abs(days_left)} days — schedule immediately.")

    # ── Idle / inactive ────────────────────────────────────────────────────────
    status = (item.status or "").lower()
    if status in IDLE_STATUSES and purchase_cost >= HIGH_VALUE_THRESHOLD:
        flags.append({"rule": "idle_high_value", "detail": f"Status: {item.status}, Value: ₹{purchase_cost:,.0f}"})
        urgency += 15
        recommend.append(
            f"High-value asset (₹{purchase_cost:,.0f}) is idle — reassign or dispose."
        )

    # ── Replace recommendation ─────────────────────────────────────────────────
    replace_triggers = {f["rule"] for f in flags}
    should_replace = (
        "age_limit" in replace_triggers and
        ("critical_condition" in replace_triggers or "high_repair_cost" in replace_triggers)
    )

    return {
        "asset_id":     item.id,
        "name":         item.name,
        "asset_code":   item.asset_code,
        "urgency":      urgency,
        "flags":        flags,
        "recommend_replace": should_replace,
        "recommendations": list(dict.fromkeys(recommend)),  # deduplicate, preserve order
    }


# ── Batch evaluator ────────────────────────────────────────────────────────────

def evaluate_all_assets(company_id: int) -> Dict[str, Any]:
    """
    Run rules on every asset for a company.
    Returns priority-sorted list and summary counts.
    """
    from models import InventoryItem, ServiceLog

    items = InventoryItem.query.filter_by(company_id=company_id).all()

    # Pre-fetch service logs grouped by item_id to avoid N+1
    all_logs = ServiceLog.query.join(InventoryItem).filter(
        InventoryItem.company_id == company_id
    ).all()
    logs_by_item: Dict[int, List] = {}
    for log in all_logs:
        logs_by_item.setdefault(log.item_id, []).append(log)

    results = []
    for item in items:
        logs = logs_by_item.get(item.id, [])
        result = evaluate_asset(item, service_logs=logs)
        if result["flags"]:  # only include assets with at least one issue
            results.append(result)

    results.sort(key=lambda x: x["urgency"], reverse=True)

    replace_list = [r for r in results if r["recommend_replace"]]
    critical     = [r for r in results if r["urgency"] >= 50]
    attention    = [r for r in results if 20 <= r["urgency"] < 50]

    return {
        "intent":           "rules_evaluation",
        "total_assets":     len(items),
        "assets_with_issues": len(results),
        "replace_count":    len(replace_list),
        "critical_count":   len(critical),
        "attention_count":  len(attention),
        "replace_list":     replace_list[:10],
        "top_issues":       results[:15],
    }


# ── Single-asset recommendation ────────────────────────────────────────────────

def should_replace_asset(item_id: int, company_id: int) -> Dict[str, Any]:
    """Evaluate replacement decision for a specific asset."""
    from models import InventoryItem, ServiceLog

    item = InventoryItem.query.filter_by(id=item_id, company_id=company_id).first()
    if not item:
        return {"error": "Asset not found"}

    logs = ServiceLog.query.filter_by(item_id=item_id).all()
    return evaluate_asset(item, service_logs=logs)
