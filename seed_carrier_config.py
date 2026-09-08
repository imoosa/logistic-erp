# Run once, standalone, after the app boots with the new tables created:
#   python seed_carrier_config.py
#
# Every URL template below is UNVERIFIED. Confirm each one manually with a
# real docket number before flipping is_active=True. Deliberately left
# False on every row until you do.
from app import app
from platform_models import db, CarrierTrackingConfig

SEED = [
    ("BLUEDART",  "Blue Dart",  "https://www.bluedart.com/tracking?trackFor=0&trackNo={tracking_number}"),
    ("DHL",       "DHL",        "https://www.dhl.com/in-en/home/tracking.html?tracking-id={tracking_number}"),
    ("DTDC",      "DTDC",       "https://www.dtdc.in/tracking.asp?strCnno={tracking_number}"),
    ("DELHIVERY", "Delhivery",  "https://www.delhivery.com/track/package/{tracking_number}"),
    ("FEDEX",     "FedEx",      "https://www.fedex.com/fedextrack/?trknbr={tracking_number}"),
    ("ARAMEX",    "Aramex",     "https://www.aramex.com/track/results?ShipmentNumber={tracking_number}"),
]

with app.app_context():
    for carrier_key, display_name, url_template in SEED:
        if CarrierTrackingConfig.query.filter_by(carrier_key=carrier_key).first():
            continue
        db.session.add(CarrierTrackingConfig(
            carrier_key=carrier_key, display_name=display_name,
            tracking_url_template=url_template, is_active=False,
        ))
    db.session.commit()
    print("Seeded — all inactive until you verify each URL manually.")
