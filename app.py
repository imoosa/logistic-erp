from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from flask import abort
from datetime import date, datetime, timedelta
import random
import hashlib
import secrets
from functools import wraps
import os
import json
import re
import pandas as pd
from werkzeug.utils import secure_filename
import io
import base64
from sqlalchemy import text, func, and_, or_
from platform_models import db, SubscriptionPlan, RegisteredUser, Company
from customer_models import (
    CompanyUser, Client, Order, StockItem,
    Invoice, InvoiceItem,
    Estimate, EstimateItem,
    PurchaseInvoice, PurchaseInvoiceItem, StockPurchaseHistory,
    CashTransaction, Loan, LoanRepayment,
    BankAccount, BankTransaction, CompanyManifest, ManifestEntry, Expense, Supplier,
    PriceList, RateLookup)
from db_router import get_customer_session, init_customer_db_for_company
from backup_utils import BACKUP_DESTINATIONS

app = Flask(__name__)
app.secret_key = "nexa-erp-2024-super-secret-key-change-in-production"

@app.template_filter('from_json')
def from_json_filter(value):
    """Parse JSON string to Python object in templates"""
    if not value:
        return {}
    try:
        return json.loads(value)
    except (ValueError, TypeError, json.JSONDecodeError):
        return {}

# Also add a filter for JSON parsing with default
@app.template_filter('json_loads')
def json_loads_filter(value, default=None):
    """Parse JSON string to Python object in templates"""
    if not value:
        return default or {}
    try:
        return json.loads(value)
    except (ValueError, TypeError, json.JSONDecodeError):
        return default or {}

# ── Database Configuration ────────────────────────────────────────────────────
PLATFORM_DB_URI = os.environ.get(
    "PLATFORM_DB_URI",
    "mysql+pymysql://root@localhost/logistic_erp"   # ← change this default
)
app.config["SQLALCHEMY_DATABASE_URI"] = PLATFORM_DB_URI
app.config["SQLALCHEMY_BINDS"] = {}          # customer DBs are managed by db_router, not binds
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

@app.before_request
def _fk_on():
    pass  # MySQL enforces FK by default; no PRAGMA needed

with app.app_context():
    db.create_all()

"""app.config["SQLALCHEMY_DATABASE_URI"] = (
    'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'maktroniks.db')
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

@app.before_request
def before_request():
    if db.engine.url.drivername == 'sqlite':
        db.session.execute(text('PRAGMA foreign_keys=ON'))

db.init_app(app)"""

# ── Create tables and seed on first startup ────────────────────────────────────
with app.app_context():
    # Only create platform tables - customer DBs are created per-company
    db.create_all()

UPLOAD_FOLDER = 'uploads/purchase_invoices'
ALLOWED_EXTENSIONS = {
    'png',
    'jpg',
    'jpeg',
    'pdf',
    'tiff',
    'bmp',
    'xlsx',
    'xls'
}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ── Helper / Auth ─────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed

def get_current_user():
    return session.get("user", {})

@app.context_processor
def inject_user():
    return {
        "user": session.get("user", {}),
    }

@app.context_processor
def inject_company_settings():
    company_id = get_current_company()
    is_gst = True  # default safe
    if company_id:
        co = Company.query.filter_by(company_id=company_id).first()
        if co and hasattr(co, 'is_gst_registered'):
            is_gst = bool(co.is_gst_registered)
    return {'is_gst_registered': is_gst}

def get_current_company():
    return session.get("active_company_id") or session.get("user", {}).get("company_id")

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please login to continue")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def owner_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if user.get("role") not in ["owner", "super_admin"]:
            flash("Only company owner can access this page")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated

def super_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if user.get("role") != "super_admin":
            flash("Super admin access required")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated

# ── Seed Data ─────────────────────────────────────────────────────────────────
SUBSCRIPTION_PLANS_DATA = {
    "basic": {
        "name": "Basic Plan",
        "price": "999",
        "max_companies": "2",
        "max_users": "5",
        "features": "Basic Analytics,Order Management,Client Management,Email Support",
    },
    "premium": {
        "name": "Premium Plan",
        "price": "2499",
        "max_companies": "5",
        "max_users": "15",
        "features": "Advanced Analytics,Inventory Management,Invoice & Estimates,Priority Support,API Access",
    },
    "gold": {
        "name": "Gold Plan",
        "price": "4999",
        "max_companies": "10",
        "max_users": "35",
        "features": "All Premium Features,Custom Reports,Dedicated Account Manager,24/7 Support,White-label Option",
    },
    "custom": {
        "name": "Custom Plan",
        "price": "Contact Sales",
        "max_companies": "Unlimited",
        "max_users": "Unlimited",
        "features": "Fully Customizable,On-premise Deployment,Training Included,Custom Development",
    },
}

def seed_database():
    """Insert initial plans, users and sample data if the DB is empty."""
    
    # ── Subscription Plans (Platform DB) ─────────────────────────────────────
    if SubscriptionPlan.query.count() == 0:
        for plan_id, data in SUBSCRIPTION_PLANS_DATA.items():
            db.session.add(SubscriptionPlan(
                id=plan_id,
                name=data["name"],
                price=data["price"],
                max_companies=data["max_companies"],
                max_users=data["max_users"],
                features=data["features"],
            ))
        db.session.commit()
        print("✔  Subscription plans seeded.")

    # ── Registered Users (Platform DB) ──────────────────────────────────────
    if RegisteredUser.query.count() == 0:
        admin = RegisteredUser(
            user_id="USR001",
            email="admin@nexa.com",
            password_hash=hash_password("Admin@123"),
            full_name="System Admin",
            phone="9999999999",
            role="super_admin",
            subscription_plan=None,
            created_at=date(2024, 1, 1),
            is_active=True,
        )
        rahul = RegisteredUser(
            user_id="USR002",
            email="rahul@techsolutions.com",
            password_hash=hash_password("Tech@123"),
            full_name="Rahul Sharma",
            phone="9876543210",
            role="owner",
            subscription_plan="premium",
            created_at=date(2024, 1, 1),
            is_active=True,
        )
        priya_reg = RegisteredUser(
            user_id="USR003",
            email="priya@globaltraders.com",
            password_hash=hash_password("Global@123"),
            full_name="Priya Singh",
            phone="9876543211",
            role="owner",
            subscription_plan="basic",
            created_at=date(2024, 1, 15),
            is_active=True,
        )
        db.session.add_all([admin, rahul, priya_reg])
        db.session.commit()
        print("✔  Registered users seeded.")

    # ── Companies (Platform DB) ─────────────────────────────────────────────
    if Company.query.count() == 0:
        comp1 = Company(
            company_id="COMP001",
            company_name="Tech Solutions India",
            owner_email="rahul@techsolutions.com",
            subscription_plan="premium",
            subscription_start=date(2024, 1, 1),
            subscription_end=date(2025, 1, 1),
            max_companies_allowed="5",
            max_users_per_company="15",
            gst_number="27AAABC1234F1Z",
            address="Mumbai, Maharashtra",
            phone="9876543210",
            created_at=date(2024, 1, 1),
            is_active=True,

        )
        comp2 = Company(
            company_id="COMP002",
            company_name="Global Traders Ltd",
            owner_email="priya@globaltraders.com",
            subscription_plan="basic",
            subscription_start=date(2024, 1, 15),
            subscription_end=date(2024, 7, 15),
            max_companies_allowed="2",
            max_users_per_company="5",
            gst_number="29AABCB5678F1Z",
            address="Delhi, India",
            phone="9876543211",
            created_at=date(2024, 1, 15),
            is_active=True,
        )
        comp3 = Company(
            company_id="COMP003",
            company_name="Rahul Exports Pvt Ltd",
            owner_email="rahul@techsolutions.com",
            subscription_plan="premium",
            subscription_start=date(2024, 3, 1),
            subscription_end=date(2025, 3, 1),
            max_companies_allowed="5",
            max_users_per_company="15",
            gst_number="27AAABC9999F1Z",
            address="Pune, Maharashtra",
            phone="9876543299",
            created_at=date(2024, 3, 1),
            is_active=True,
        )
        db.session.add_all([comp1, comp2, comp3])
        db.session.commit()
        print("✔  Companies seeded.")
    
    print("✅ Platform database seeding complete.")

def seed_customer_database(company_id):
    """Seed customer data for a specific company in its own database."""
    from db_router import get_customer_session
    
    cdb = get_customer_session(company_id, db_session=db.session)
    
    # ── Company Users ───────────────────────────────────────────────────────
    if cdb.query(CompanyUser).count() == 0:
        # Get company info to know the owner
        company = Company.query.filter_by(company_id=company_id).first()
        owner_reg = RegisteredUser.query.filter_by(email=company.owner_email).first()
        
        users = [
            CompanyUser(
                user_id="EMP001",
                company_id=company_id,
                email=company.owner_email,
                password_hash=hash_password("Tech@123"),  # Use appropriate default
                full_name=owner_reg.full_name if owner_reg else "Owner",
                role="owner",
                department="Management",
                phone=company.phone,
                is_active=True,
                created_at=date.today()
            ),
        ]
        
        # Add sample users for COMP001 only
        if company_id == "COMP001":
            users.extend([
                CompanyUser(
                    user_id="EMP002",
                    company_id=company_id,
                    email="priya.mehta@techsolutions.com",
                    password_hash=hash_password("Priya@123"),
                    full_name="Priya Mehta",
                    role="sales_manager",
                    department="Sales",
                    phone="9876543202",
                    is_active=True,
                    created_at=date(2024, 1, 1)
                ),
                CompanyUser(
                    user_id="EMP003",
                    company_id=company_id,
                    email="arjun.nair@techsolutions.com",
                    password_hash=hash_password("Arjun@123"),
                    full_name="Arjun Nair",
                    role="accountant",
                    department="Accounts",
                    phone="9876543203",
                    is_active=True,
                    created_at=date(2024, 1, 2)
                ),
            ])
        
        cdb.add_all(users)
        cdb.commit()
        print(f"✔  Company users seeded for {company_id}")

    # ── Clients ─────────────────────────────────────────────────────────────
    if cdb.query(Client).count() == 0 and company_id == "COMP001":
        clients = [
            Client(company_id=company_id, name="ABC Electronics", client_type="Customer",
                   phone="9876543220", status="Active", created_at=date.today()),
            Client(company_id=company_id, name="XYZ Traders", client_type="Customer",
                   phone="9876543221", status="Active", created_at=date.today()),
            Client(company_id=company_id, name="PQR Solutions", client_type="Business",
                   phone="9876543222", status="Active", created_at=date.today()),
            Client(company_id=company_id, name="Reliance Industries", phone="9876543210",
                   pending=0, last_payment=date(2024, 1, 22), status="Paid"),
            Client(company_id=company_id, name="Tata Consultancy", phone="9876543211",
                   pending=89500, last_payment=date(2024, 1, 5), status="Pending"),
            Client(company_id=company_id, name="Infosys Ltd", phone="9876543212",
                   pending=86000, last_payment=date(2024, 1, 18), status="Active"),
        ]
        cdb.add_all(clients)
        cdb.commit()
        print(f"✔  Clients seeded for {company_id}")
    elif cdb.query(Client).count() == 0 and company_id == "COMP002":
        clients = [
            Client(company_id=company_id, name="MNO Enterprises", client_type="Customer",
                   phone="9876543223", status="Active", created_at=date.today()),
            Client(company_id=company_id, name="HDFC Bank", phone="9876543217",
                   pending=156000, last_payment=date(2024, 1, 1), status="Pending"),
            Client(company_id=company_id, name="ICICI Bank", phone="9876543218",
                   pending=0, last_payment=date(2024, 1, 21), status="Paid"),
        ]
        cdb.add_all(clients)
        cdb.commit()
        print(f"✔  Clients seeded for {company_id}")

    # ── Stock Items ─────────────────────────────────────────────────────────
    if cdb.query(StockItem).count() == 0 and company_id == "COMP001":
        items = [
            StockItem(company_id=company_id, code="PROD001", name="LED TV 43 inch",
                      category="Electronics", quantity=25, unit="pcs", unit_price=35000,
                      reorder_level=10, last_updated=date(2024, 1, 20)),
            StockItem(company_id=company_id, code="PROD002", name="Smartphone X",
                      category="Electronics", quantity=50, unit="pcs", unit_price=25000,
                      reorder_level=20, last_updated=date(2024, 1, 20)),
        ]
        cdb.add_all(items)
        cdb.commit()
        print(f"✔  Stock items seeded for {company_id}")

    # ── Orders ──────────────────────────────────────────────────────────────
    if cdb.query(Order).count() == 0 and company_id == "COMP001":
        # Get client IDs from the clients we just added
        clients_dict = {c.name: c.id for c in cdb.query(Client).all()}
        
        orders = [
            Order(order_id="ORD-2024-001", company_id=company_id,
                  client_id=clients_dict.get("Reliance Industries"),
                  employee_id="EMP001", date=date(2024, 1, 15),
                  amount=245000, received=245000, status="Delivered"),
            Order(order_id="ORD-2024-002", company_id=company_id,
                  client_id=clients_dict.get("Tata Consultancy"),
                  employee_id="EMP002", date=date(2024, 1, 17),
                  amount=89500, received=0, status="Pending"),
            Order(order_id="ORD-2024-003", company_id=company_id,
                  client_id=clients_dict.get("Infosys Ltd"),
                  employee_id="EMP001", date=date(2024, 1, 18),
                  amount=172000, received=86000, status="Processing"),
        ]
        cdb.add_all(orders)
        cdb.commit()
        print(f"✔  Orders seeded for {company_id}")

    # Close the session
    from db_router import close_customer_session
    close_customer_session(company_id)


# ── Plan helper ───────────────────────────────────────────────────────────────
def get_plan(plan_id):
    p = SubscriptionPlan.query.get(plan_id)
    if not p:
        return {}
    return {
        "name": p.name,
        "price": p.price,
        "max_companies": p.max_companies,
        "max_users_per_company": p.max_users,
        "features": p.features.split(",") if p.features else [],
    }

def get_all_plans():
    return {p.id: get_plan(p.id) for p in SubscriptionPlan.query.all()}


# ── Company helpers ───────────────────────────────────────────────────────────
def get_company_by_id(company_id):
    return Company.query.filter_by(company_id=company_id).first()

def get_owner_companies(owner_email):
    return Company.query.filter_by(owner_email=owner_email, is_active=True).all()

def check_company_limit(company_id, user_type="user"):
    company = get_company_by_id(company_id)
    if not company:
        return False, "Company not found"
    plan = get_plan(company.subscription_plan)
    if user_type == "user":
        _cdb = get_customer_session(company_id)
        current = _cdb.query(CompanyUser).filter_by(company_id=company_id, is_active=True).count()
        max_u = plan.get("max_users_per_company", 5)
        try:
            max_u = int(max_u)
            if current >= max_u:
                return False, f"Maximum {max_u} users allowed in your {plan['name']}. Please upgrade."
        except (ValueError, TypeError):
            pass  # "Unlimited"
    return True, "OK"

def check_new_company_limit(owner_email):
    comps = get_owner_companies(owner_email)
    if not comps:
        return True, "OK"
    plan = get_plan(comps[0].subscription_plan)
    max_c = plan.get("max_companies", 2)
    try:
        max_c = int(max_c)
        if len(comps) >= max_c:
            return False, f"Your {plan['name']} allows up to {max_c} companies. Please upgrade."
    except (ValueError, TypeError):
        pass  # "Unlimited"
    return True, "OK"


def get_cdb():
    """
    Return a customer-database session for the currently active company.
    Use this everywhere you previously used db.session for customer tables.

    Example:
        cdb = get_cdb()
        clients = cdb.query(Client).filter_by(company_id=company_id).all()
    """
    company_id = get_current_company()
    if not company_id:
        return None
    return get_customer_session(company_id, db_session=db.session)

def _first_or_404(obj):
    """Replacement for Flask-SQLAlchemy's first_or_404() for plain SQLAlchemy queries."""
    if obj is None:
        from flask import abort
        abort(404)
    return obj

def parse_price_list(df, courier):
    """Parse Excel price list into structured JSON"""
    import re
    
    data = {
        'courier': courier,
        'format': 'unknown',
        'countries': {},
        'weights': []
    }
    
    headers = df.columns.tolist()
    
    print(f"📊 Parsing {courier} - Columns found: {headers}")
    
    # DPD Format: Has COUNTRY column
    country_col = None
    for h in headers:
        if 'COUNTRY' in str(h).upper() or 'Country' in str(h):
            country_col = h
            break
    
    if country_col:
        print(f"✅ Found country column: {country_col}")
        data['format'] = 'dpd'
        
        # Find all weight columns
        weight_cols = []
        for h in headers:
            h_str = str(h).upper()
            if h == country_col:
                continue
            if 'TIME' in h_str or 'DAY' in h_str:
                continue
            if 'KG' in h_str:
                # Extract weight value
                weight_str = re.sub(r'[^\d.]', '', h_str)
                try:
                    weight_val = float(weight_str)
                    weight_cols.append((h, weight_val))
                    print(f"   Weight column: {h} -> {weight_val}kg")
                except:
                    print(f"   Could not parse weight from: {h}")
        
        weight_cols.sort(key=lambda x: x[1])
        data['weights'] = [w[1] for w in weight_cols]
        
        # Parse each row
        for idx, row in df.iterrows():
            country = str(row[country_col]).strip().upper()
            if not country or country == 'NAN' or country == 'NONE' or country == '':
                continue
            
            rates = {}
            for col_name, weight_val in weight_cols:
                try:
                    val = row[col_name]
                    if pd.notna(val) and val != '':
                        # Store weight as float key
                        rates[float(weight_val)] = float(val)
                except Exception as e:
                    print(f"   Error parsing {col_name}: {e}")
            
            if rates:
                data['countries'][country] = rates
                print(f"   Added {country}: {list(rates.keys())}")
        
        print(f"✅ Parsed {len(data['countries'])} countries for {courier}")
        if data['countries']:
            sample = list(data['countries'].keys())[0]
            print(f"   Sample: {sample} -> {data['countries'][sample]}")
        
        return data
    
    # FEDEX Format: Has WEIGHT column
    weight_col = None
    for h in headers:
        if 'WEIGHT' in str(h).upper() or 'Weight' in str(h):
            weight_col = h
            break
    
    if weight_col:
        print(f"✅ Found weight column: {weight_col}")
        data['format'] = 'fedex'
        
        country_cols = [h for h in headers if h != weight_col]
        
        for idx, row in df.iterrows():
            weight_val = float(row[weight_col]) if pd.notna(row[weight_col]) else 0
            if weight_val > 0:
                data['weights'].append(weight_val)
                for col in country_cols:
                    country_list = str(col).replace('_', '/').split('/')
                    for country in country_list:
                        country = country.strip().upper()
                        if country and len(country) > 1 and 'TIME' not in country:
                            if country not in data['countries']:
                                data['countries'][country] = {}
                            val = float(row[col]) if pd.notna(row[col]) else 0
                            # Store weight as float key
                            data['countries'][country][float(weight_val)] = val
        
        data['weights'] = sorted(set(data['weights']))
        print(f"✅ Parsed {len(data['countries'])} countries for {courier}")
        return data
    
    print(f"❌ Could not detect format for {courier}. Headers: {headers}")
    return data

# ─────────────────────────────────────────────────────────────────────────────
# ── Auth Routes ───────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        # Super-admin / registered-user login
        reg_user = RegisteredUser.query.filter_by(email=email, is_active=True).first()
        if reg_user and verify_password(password, reg_user.password_hash):
            if reg_user.role == "super_admin":
                session["user"] = {
                    "user_id": reg_user.user_id, "email": reg_user.email,
                    "full_name": reg_user.full_name, "role": "super_admin",
                    "company_id": None,
                }
                return redirect(url_for("admin_dashboard"))

            # Owner: may have multiple companies
            companies = get_owner_companies(email)
            if len(companies) == 1:
                c = companies[0]
                session["user"] = {
                    "user_id": reg_user.user_id, "email": reg_user.email,
                    "full_name": reg_user.full_name, "role": reg_user.role,
                    "company_id": c.company_id,
                }
                session["active_company_id"] = c.company_id
                return redirect(url_for("dashboard"))
            elif len(companies) > 1:
                session["pending_login_email"] = email
                return redirect(url_for("select_company"))

        # Company employee login — search each company's DB
        emp = None
        for comp in Company.query.filter_by(is_active=True).all():
            try:
                _cdb = get_customer_session(comp.company_id)
                _emp = _cdb.query(CompanyUser).filter_by(email=email, is_active=True).first()
                if _emp:
                    emp = _emp
                    break
            except Exception:
                continue
        if emp and verify_password(password, emp.password_hash):
            session["user"] = {
                "user_id": emp.user_id, "email": emp.email,
                "full_name": emp.full_name, "role": emp.role,
                "company_id": emp.company_id,
            }
            session["active_company_id"] = emp.company_id
            return redirect(url_for("dashboard"))

        flash("Invalid email or password")
    return render_template("login.html")


@app.route("/company/add", methods=["GET", "POST"])
@login_required
@owner_required
def add_new_company():
    
    company_id = get_current_company()
    user = get_current_user()
    
    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        gst_number = request.form.get("gst_number", "")
        address = request.form.get("address", "")
        phone = request.form.get("phone", "")
        
        if not company_name:
            flash("Company name is required")
            return redirect(url_for("add_new_company"))
        
        # Check if user can add more companies based on their plan
        can_add, message = check_new_company_limit(user.get("email"))
        if not can_add:
            flash(message)
            return redirect(url_for("company_settings"))
        
        # Create new company
        comp_count = Company.query.count()
        new_company_id = f"COMP{comp_count + 1:03d}"
        
        # Get user's plan
        reg_user = RegisteredUser.query.filter_by(email=user.get("email")).first()
        plan = reg_user.subscription_plan if reg_user else "basic"
        plan_obj = SubscriptionPlan.query.get(plan) or SubscriptionPlan.query.get("basic")

        is_gst = request.form.get('is_gst_registered', '1') == '1'
        gst_number = request.form.get('gst_number', '').strip() if is_gst else ''
        
        new_company = Company(
            company_id=new_company_id,
            company_name=company_name,
            owner_email=user.get("email"),
            subscription_plan=plan,
            subscription_start=date.today(),
            subscription_end=date.today() + timedelta(days=365),
            max_companies_allowed=plan_obj.max_companies,
            max_users_per_company=plan_obj.max_users,
            gst_number=gst_number if is_gst else '',
            address=address,
            phone=phone,
            created_at=date.today(),
            is_active=True,
            is_gst_registered=is_gst,
        )
        db.session.add(new_company)
        db.session.commit()

        # ── Create dedicated VPS MySQL database and all customer tables ────────
        init_customer_db_for_company(new_company)

        # ── Create the owner as first CompanyUser in the new customer DB ───────
        cdb = get_customer_session(new_company_id)
        emp_count = cdb.query(CompanyUser).count()
        emp_id    = f"EMP{emp_count + 1:03d}"
        new_emp   = CompanyUser(
            user_id=emp_id,
            company_id=new_company_id,
            email=user.get("email"),
            password_hash=hash_password(request.form.get("password", "Temp@123")),
            full_name=user.get("full_name", ""),
            role="owner",
            department="Management",
            phone=phone,
            is_active=True,
            created_at=date.today(),
        )
        cdb.add(new_emp)
        cdb.commit()

        flash(f"Company '{company_name}' created successfully! A dedicated database has been provisioned.")
        return redirect(url_for("dashboard"))
    
    # GET request - show the form with user's plan information
    user = get_current_user()
    reg_user = RegisteredUser.query.filter_by(email=user.get("email")).first()
    plan_key = reg_user.subscription_plan if reg_user else "basic"
    plan_obj = SubscriptionPlan.query.get(plan_key) or SubscriptionPlan.query.get("basic")
    
    # Get current companies count for this owner
    companies_count = Company.query.filter_by(owner_email=user.get("email")).count()
    max_companies_allowed = plan_obj.max_companies
    
    # Parse max companies (handle "Unlimited" string)
    if max_companies_allowed == "Unlimited":
        max_companies = None
        remaining_companies = "Unlimited"
        can_add_more = True
    else:
        max_companies = int(max_companies_allowed)
        remaining_companies = max(0, max_companies - companies_count)
        can_add_more = remaining_companies > 0
    
    plan_config = {
        "name": plan_obj.name,
        "price": plan_obj.price,
        "max_companies": plan_obj.max_companies,
        "max_users": plan_obj.max_users,
        "features": plan_obj.features.split(",") if plan_obj.features else [],
        "companies_used": companies_count,
        "remaining_companies": remaining_companies,
        "max_companies_int": max_companies,
        "can_add_more": can_add_more,
    }
    
    return render_template(
                "add_company.html",
                plan_config=plan_config,
                current_count=companies_count,
                max_companies=plan_obj.max_companies if plan_obj.max_companies == "Unlimited" else int(plan_obj.max_companies),
                can_add=can_add_more,
            )

@app.route("/select-company", methods=["GET", "POST"])
def select_company():
    owner_email = session.get("pending_login_email") or session.get("user", {}).get("email")
    if not owner_email:
        return redirect(url_for("login"))

    if request.method == "POST":
        company_id = request.form.get("company_id")
        company = get_company_by_id(company_id)
        if company and company.owner_email == owner_email:
            reg_user = RegisteredUser.query.filter_by(email=owner_email).first()
            session["user"] = {
                "email":     reg_user.email,
                "full_name": reg_user.full_name,
                "role":      reg_user.role,
                "user_id":   reg_user.user_id,
            }
            session["active_company_id"] = company_id
            session.pop("pending_login_email", None)
            return redirect(url_for("dashboard"))
        flash("Invalid company selection.")

    companies = get_owner_companies(owner_email)
    user = get_current_user()
    if not user:
        reg_user = RegisteredUser.query.filter_by(email=owner_email).first()
        user = {"full_name": reg_user.full_name, "email": reg_user.email} if reg_user else {"full_name": owner_email, "email": owner_email}
    return render_template("select_company.html", companies=companies, user=user)


@app.route("/switch-company/<company_id>")
@login_required
def switch_company(company_id):
    user = get_current_user()
    company = get_company_by_id(company_id)
    if company and company.owner_email == user.get("email"):
        session["active_company_id"] = company_id
        flash(f"Switched to {company.company_name}")
    return redirect(url_for("dashboard"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        # ── Pull owner / account fields ───────────────────────────────────────
        email            = request.form.get("email", "").strip().lower()
        password         = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        full_name        = request.form.get("full_name", "").strip()
        phone            = request.form.get("phone", "").strip()
        plan_key         = request.form.get("subscription_plan", "basic")

        # ── Pull primary company fields ───────────────────────────────────────
        company_name     = request.form.get("company_name", "").strip()
        address          = request.form.get("address", request.form.get("company_address_1", "")).strip()
        company_phone    = request.form.get("company_phone_1", phone).strip()
        is_gst           = request.form.get("is_gst_registered", "1") == "1"
        gst_number       = request.form.get("gst_number", "").strip() if is_gst else ""

        # ── Extra companies (from hidden JSON field) ──────────────────────────
        extra_companies_raw = request.form.get("extra_companies", "[]")
        try:
            extra_companies = json.loads(extra_companies_raw)
            if not isinstance(extra_companies, list):
                extra_companies = []
        except (ValueError, TypeError):
            extra_companies = []

        # ── Validations ───────────────────────────────────────────────────────
        if not email:
            flash("Email is required", "error")
            return redirect(url_for("register"))

        if RegisteredUser.query.filter_by(email=email).first():
            flash("An account with this email already exists", "error")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match", "error")
            return redirect(url_for("register"))

        if len(password) < 8:
            flash("Password must be at least 8 characters", "error")
            return redirect(url_for("register"))

        if not company_name:
            flash("Company name is required", "error")
            return redirect(url_for("register"))

        # ── Plan lookup ───────────────────────────────────────────────────────
        plan_obj = SubscriptionPlan.query.get(plan_key) or SubscriptionPlan.query.get("basic")
        end_days = 730 if plan_obj.id == "custom" else 365

        # ── Check extra companies don't exceed plan limit ─────────────────────
        max_c = plan_obj.max_companies
        try:
            max_c_int = int(max_c)
            total_requested = 1 + len(extra_companies)
            if total_requested > max_c_int:
                flash(
                    f"Your {plan_obj.name} allows up to {max_c_int} "
                    f"{'company' if max_c_int == 1 else 'companies'}. "
                    f"You requested {total_requested}.",
                    "error"
                )
                return redirect(url_for("register"))
        except (ValueError, TypeError):
            pass  # "Unlimited" — no cap

        # ── Create RegisteredUser (platform DB) ───────────────────────────────
        reg_count = RegisteredUser.query.count()
        user_id   = f"USR{reg_count + 1:03d}"

        new_user = RegisteredUser(
            user_id=user_id,
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            phone=phone,
            role="owner",
            subscription_plan=plan_obj.id,
            created_at=date.today(),
            is_active=True,
        )
        db.session.add(new_user)
        db.session.flush()  # get id without committing

        # ── Helper: create one Company record + its customer DB ───────────────
        def _create_company(c_name, c_address, c_phone, c_gst_registered, c_gst_number):
            comp_count = Company.query.count()
            c_id       = f"COMP{comp_count + 1:03d}"

            company = Company(
                company_id=c_id,
                company_name=c_name,
                owner_email=email,
                subscription_plan=plan_obj.id,
                subscription_start=date.today(),
                subscription_end=date.today() + timedelta(days=end_days),
                max_companies_allowed=plan_obj.max_companies,
                max_users_per_company=plan_obj.max_users,
                address=c_address,
                phone=c_phone or phone,
                gst_number=c_gst_number if c_gst_registered else "",
                is_gst_registered=c_gst_registered,
                created_at=date.today(),
                is_active=True,
                # storage_type always 'cloud' — managed by Nexa, no user choice needed
                storage_type="cloud",
            )
            db.session.add(company)
            db.session.flush()  # make company_id available before commit

            return c_id

        # ── Create primary company ─────────────────────────────────────────────
        primary_company_id = _create_company(
            company_name, address, company_phone, is_gst, gst_number
        )

        # ── Create extra companies ────────────────────────────────────────────
        extra_company_ids = []
        for ec in extra_companies:
            ec_name = ec.get("name", "").strip()
            if not ec_name:
                continue
            ec_id = _create_company(
                ec_name,
                ec.get("address", ""),
                ec.get("phone", ""),
                bool(ec.get("is_gst_registered", True)),
                ec.get("gst_number", ""),
            )
            extra_company_ids.append(ec_id)

        # ── Commit all platform records at once ───────────────────────────────
        db.session.commit()

        # ── Bootstrap customer databases ──────────────────────────────────────
        all_company_ids = [primary_company_id] + extra_company_ids

        for c_id in all_company_ids:
            try:
                company_obj = Company.query.filter_by(company_id=c_id).first()
                init_customer_db_for_company(company_obj)
            except Exception as e:
                print(f"⚠  Could not init customer DB for {c_id}: {e}")

        # ── Create owner as CompanyUser in primary company's DB ───────────────
        try:
            cdb       = get_customer_session(primary_company_id)
            emp_count = cdb.query(CompanyUser).count()
            emp_id    = f"EMP{emp_count + 1:03d}"

            new_emp = CompanyUser(
                user_id=emp_id,
                company_id=primary_company_id,
                email=email,
                password_hash=hash_password(password),
                full_name=full_name,
                role="owner",
                department="Management",
                phone=phone,
                is_active=True,
                created_at=date.today(),
            )
            cdb.add(new_emp)
            cdb.commit()
        except Exception as e:
            print(f"⚠  Could not create CompanyUser for {primary_company_id}: {e}")

        # ── Also add owner as CompanyUser in any extra company DBs ────────────
        for c_id in extra_company_ids:
            try:
                cdb       = get_customer_session(c_id)
                emp_count = cdb.query(CompanyUser).count()
                emp_id    = f"EMP{emp_count + 1:03d}"
                extra_emp = CompanyUser(
                    user_id=emp_id,
                    company_id=c_id,
                    email=email,
                    password_hash=hash_password(password),
                    full_name=full_name,
                    role="owner",
                    department="Management",
                    phone=phone,
                    is_active=True,
                    created_at=date.today(),
                )
                cdb.add(extra_emp)
                cdb.commit()
            except Exception as e:
                print(f"⚠  Could not create CompanyUser for {c_id}: {e}")

        total = len(all_company_ids)
        flash(
            f"Welcome to Nexa ERP! Your account and "
            f"{total} {'company has' if total == 1 else 'companies have'} been set up. Please login.",
            "success"
        )
        return redirect(url_for("login"))

    return render_template("register.html", plans=get_all_plans())

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))



# ─────────────────────────────────────────────────────────────────────────────
# ── Dashboard ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/reports-dashboard")
@login_required
def reports_dashboard():
    
    company_id = get_current_company()
    company = get_company_by_id(company_id)
    
    if not company:
        flash("Company not found")
        return redirect(url_for("logout"))
    
    cdb = get_cdb()
    if not cdb:
        flash("Could not connect to company database")
        return redirect(url_for("logout"))
    
    # Set default dates (current month)
    from_date = date.today().replace(day=1)
    to_date = date.today()
    
    # Get initial data for the template
    # Cash in Hand
    cash_transactions = cdb.query(CashTransaction).filter_by(company_id=company_id).all()
    cash_balance = sum(t.amount for t in cash_transactions if t.type == 'income') - \
                   sum(t.amount for t in cash_transactions if t.type == 'expense')
    
    # Bank Balance
    bank_accounts = cdb.query(BankAccount).filter_by(company_id=company_id, status='Active').all()
    bank_balance = sum(acc.balance for acc in bank_accounts)
    
    # Total Revenue (current month)
    sales_invoices = cdb.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.date >= from_date,
        Invoice.date <= to_date
    ).all()
    total_revenue = sum(float(inv.grand_total or 0) for inv in sales_invoices)
    
    # Total Purchases (current month)
    purchase_invoices = cdb.query(PurchaseInvoice).filter(
        PurchaseInvoice.company_id == company_id,
        PurchaseInvoice.date >= from_date,
        PurchaseInvoice.date <= to_date
    ).all()
    total_purchases = sum(float(pur.grand_total or 0) for pur in purchase_invoices)
    
    # Profit
    profit = total_revenue - total_purchases
    
    # Pending Amount
    all_invoices = cdb.query(Invoice).filter_by(company_id=company_id).all()
    pending_amount = sum(float(getattr(inv, 'balance', 0) or 0) for inv in all_invoices)
    
    # Cash flow for period
    period_cash_income = cdb.query(CashTransaction).filter(
        CashTransaction.company_id == company_id,
        CashTransaction.type == 'income',
        CashTransaction.date >= from_date,
        CashTransaction.date <= to_date
    ).all()
    period_cash_expense = cdb.query(CashTransaction).filter(
        CashTransaction.company_id == company_id,
        CashTransaction.type == 'expense',
        CashTransaction.date >= from_date,
        CashTransaction.date <= to_date
    ).all()
    cash_inflow_period = sum(t.amount for t in period_cash_income)
    cash_outflow_period = sum(t.amount for t in period_cash_expense)
    cash_net_period = cash_inflow_period - cash_outflow_period
    
    # Chart Data (Last 6 months)
    chart_labels = []
    revenue_data = []
    purchase_data = []
    profit_trend = []
    profit_labels = []
    
    for i in range(5, -1, -1):
        month_date = date.today().replace(day=1) - timedelta(days=30 * i)
        month_start = month_date.replace(day=1)
        if month_date.month == 12:
            month_end = month_date.replace(day=31)
        else:
            month_end = month_date.replace(month=month_date.month + 1, day=1) - timedelta(days=1)
        
        month_label = month_date.strftime('%b %Y')
        chart_labels.append(month_label)
        
        month_revenue = sum(
            float(inv.grand_total or 0) for inv in cdb.query(Invoice).filter(
                Invoice.company_id == company_id,
                Invoice.date >= month_start,
                Invoice.date <= month_end
            ).all()
        )
        revenue_data.append(month_revenue / 100000)

        month_purchases = sum(
            float(pur.grand_total or 0) for pur in cdb.query(PurchaseInvoice).filter(
                PurchaseInvoice.company_id == company_id,
                PurchaseInvoice.date >= month_start,
                PurchaseInvoice.date <= month_end
            ).all()
        )
        purchase_data.append(month_purchases / 100000)

        month_profit = month_revenue - month_purchases
        profit_trend.append(month_profit / 1000)
        profit_labels.append(month_label)
    
    # Status counts for all shipments
    all_customer_invoices = cdb.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.invoice_id.like("CUST-%")
    ).all()
    
    status_counts = {
        "delivered": sum(1 for i in all_customer_invoices if i.status == "Paid"),
        "in_transit": sum(1 for i in all_customer_invoices if i.status == "Partial"),
        "pending": sum(1 for i in all_customer_invoices if i.status not in ["Paid", "Partial", "Draft"]),
        "draft": sum(1 for i in all_customer_invoices if i.status == "Draft"),
        "total": len(all_customer_invoices)
    }
    
    # Payment methods breakdown
    cash_txns = cdb.query(CashTransaction).filter_by(company_id=company_id, type='income').all()
    bank_txns = cdb.query(BankTransaction).filter_by(company_id=company_id, type='credit').all()
    
    payment_methods = {
        "Cash": sum(t.amount for t in cash_txns),
        "Online/UPI": sum(t.amount for t in bank_txns if t.transaction_mode == "Online"),
        "Cheque": sum(t.amount for t in bank_txns if t.transaction_mode == "Cheque"),
    }
    
    # Top clients
    clients = cdb.query(Client).filter_by(company_id=company_id).all()
    top_clients_data = []
    for client in clients[:10]:
        client_invoices = cdb.query(Invoice).filter_by(company_id=company_id, client_id=client.id).all()
        client_shipments = [i for i in client_invoices if i.invoice_id.startswith("CUST-")]
        total_billed = sum(float(inv.grand_total or 0) for inv in client_invoices)
        pending = sum(float(getattr(inv, 'balance', 0) or 0) for inv in client_invoices)
        top_clients_data.append({
            "name": client.name,
            "total_billed": total_billed,
            "pending": pending,
            "shipment_count": len(client_shipments)
        })
    top_clients_data.sort(key=lambda x: x["total_billed"], reverse=True)
    top_clients_data = top_clients_data[:5]
    
    # Recent shipments (last 10)
    recent_shipments = []
    for inv in all_customer_invoices[:10]:
        meta = {}
        if inv.terms:
            try:
                meta = json.loads(inv.terms)
            except:
                pass
        status_label = "Delivered" if inv.status == "Paid" else "In Transit" if inv.status == "Partial" else "Pending" if inv.status != "Draft" else "Draft"
        status_class = "delivered" if inv.status == "Paid" else "transit" if inv.status == "Partial" else "pending"
        recent_shipments.append({
            "docket_no": meta.get("docket_no", inv.invoice_id),
            "customer_name": inv.client_obj.name if inv.client_obj else (inv.contact_person or "—"),
            "destination": meta.get("destination", ""),
            "total": float(inv.grand_total or 0),
            "status": inv.status,
            "status_label": status_label,
            "status_class": status_class
        })
    
    # Recent payments
    recent_payments = []
    for txn in cash_txns[:10]:
        recent_payments.append({
            "date": txn.date.strftime("%d %b %Y"),
            "customer": txn.description[:30],
            "invoice_id": txn.reference or "—",
            "amount": txn.amount,
            "mode": "Cash"
        })
    for txn in bank_txns[:5]:
        recent_payments.append({
            "date": txn.date.strftime("%d %b %Y"),
            "customer": txn.description[:30],
            "invoice_id": txn.reference or "—",
            "amount": txn.amount,
            "mode": txn.transaction_mode or "Bank"
        })
    recent_payments.sort(key=lambda x: x['date'], reverse=True)
    recent_payments = recent_payments[:10]
    
    # Pending invoices
    pending_invoices = []
    for inv in all_invoices:
        balance = float(getattr(inv, 'balance', 0) or 0)
        if balance > 0:
            pending_invoices.append({
                "invoice_id": inv.invoice_id,
                "customer": inv.client_obj.name if inv.client_obj else (inv.contact_person or "—"),
                "date": inv.date.strftime("%d %b %Y") if inv.date else "—",
                "due_date": inv.due_date.strftime("%d %b %Y") if inv.due_date else "—",
                "balance": balance
            })
    pending_invoices = pending_invoices[:10]
    
    kpi = {
        "cash_balance": cash_balance,
        "bank_balance": bank_balance,
        "total_revenue": total_revenue,
        "total_purchases": total_purchases,
        "profit": profit,
        "pending_amount": pending_amount,
        "cash_inflow_period": cash_inflow_period,
        "cash_outflow_period": cash_outflow_period,
        "cash_net_period": cash_net_period,
    }
    
    return render_template("report_dashboard.html",
                         company=company,
                         kpi=kpi,
                         from_date=from_date.strftime('%Y-%m-%d'),
                         to_date=to_date.strftime('%Y-%m-%d'),
                         chart_labels=chart_labels,
                         revenue_data=revenue_data,
                         purchase_data=purchase_data,
                         profit_labels=profit_labels,
                         profit_trend=profit_trend,
                         cash_inflow_period=cash_inflow_period,
                         cash_outflow_period=cash_outflow_period,
                         cash_net_period=cash_net_period,
                         top_clients_data=top_clients_data,
                         status_counts=status_counts,
                         payment_methods=payment_methods,
                         recent_shipments=recent_shipments,
                         recent_payments=recent_payments,
                         pending_invoices=pending_invoices,
                         total_shipments=status_counts["total"])

@app.route("/dashboard")
@login_required
def dashboard():
    """Main business dashboard"""
    company_id = get_current_company()
    company = get_company_by_id(company_id)
    
    if not company:
        flash("Company not found")
        return redirect(url_for("logout"))
    
    cdb = get_cdb()
    if not cdb:
        flash("Could not connect to company database")
        return redirect(url_for("logout"))

    # Get date filters (default to all-time to match AJAX endpoint)
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    
    if not from_date_str:
        from_date = date(2000, 1, 1)   # Show all records by default
    else:
        from_date = date.fromisoformat(from_date_str)
    
    if not to_date_str:
        to_date = date.today()
    else:
        to_date = date.fromisoformat(to_date_str)

    # Cash in Hand
    cash_transactions = cdb.query(CashTransaction).filter_by(company_id=company_id).all()
    cash_balance = sum(t.amount for t in cash_transactions if t.type == 'income') - \
                   sum(t.amount for t in cash_transactions if t.type == 'expense')
    
    # Bank Balance
    bank_accounts = cdb.query(BankAccount).filter_by(company_id=company_id, status='Active').all()
    bank_balance = sum(acc.balance for acc in bank_accounts)
    
    # Sales Invoices (Revenue)
    sales_invoices = cdb.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.date >= from_date,
        Invoice.date <= to_date
    ).all()
    total_revenue = sum(float(inv.grand_total or 0) for inv in sales_invoices)
    
    # Purchase Invoices
    purchase_invoices = cdb.query(PurchaseInvoice).filter(
        PurchaseInvoice.company_id == company_id,
        PurchaseInvoice.date >= from_date,
        PurchaseInvoice.date <= to_date
    ).all()
    total_purchases = sum(float(pur.grand_total or 0) for pur in purchase_invoices)
    
    # ── NEW: Get Expenses for the period ──────────────────────────────────────
    period_expenses = cdb.query(Expense).filter(
        Expense.company_id == company_id,
        Expense.date >= from_date,
        Expense.date <= to_date
    ).all()
    total_expenses = sum(float(exp.amount or 0) for exp in period_expenses)
    
    # ── NEW: Calculate Gross Profit (Revenue - Purchases) ────────────────────
    gross_profit = total_revenue - total_purchases
    
    # ── NEW: Calculate Net Profit (Gross Profit - Expenses) ──────────────────
    net_profit = gross_profit - total_expenses
    
    all_invoices = cdb.query(Invoice).filter_by(company_id=company_id).all()
    pending_amount = sum(float(getattr(inv, 'balance', 0) or 0) for inv in all_invoices)
    
    # Cash flow for period
    period_cash_income = cdb.query(CashTransaction).filter(
        CashTransaction.company_id == company_id,
        CashTransaction.type == 'income',
        CashTransaction.date >= from_date,
        CashTransaction.date <= to_date
    ).all()
    period_cash_expense = cdb.query(CashTransaction).filter(
        CashTransaction.company_id == company_id,
        CashTransaction.type == 'expense',
        CashTransaction.date >= from_date,
        CashTransaction.date <= to_date
    ).all()
    cash_inflow_period = sum(t.amount for t in period_cash_income)
    cash_outflow_period = sum(t.amount for t in period_cash_expense)
    cash_net_period = cash_inflow_period - cash_outflow_period
    
    # Chart Data (Last 6 months)
    chart_labels = []
    revenue_data = []
    purchase_data = []
    expense_data = [] 
    profit_trend = []
    profit_labels = []
    
    for i in range(5, -1, -1):
        month_date = date.today().replace(day=1) - timedelta(days=30 * i)
        month_start = month_date.replace(day=1)
        if month_date.month == 12:
            month_end = month_date.replace(day=31)
        else:
            month_end = month_date.replace(month=month_date.month + 1, day=1) - timedelta(days=1)
        
        month_label = month_date.strftime('%b %Y')
        chart_labels.append(month_label)
        
        month_revenue = sum(
            float(inv.grand_total or 0) for inv in cdb.query(Invoice).filter(
                Invoice.company_id == company_id,
                Invoice.date >= month_start,
                Invoice.date <= month_end
            ).all()
        )
        revenue_data.append(month_revenue / 100000)
        
        # Add purchase data for chart
        month_purchases = sum(
            float(pur.grand_total or 0) for pur in cdb.query(PurchaseInvoice).filter(
                PurchaseInvoice.company_id == company_id,
                PurchaseInvoice.date >= month_start,
                PurchaseInvoice.date <= month_end
            ).all()
        )
        purchase_data.append(month_purchases / 100000)
        
        month_expenses = sum(
            float(exp.amount or 0) for exp in cdb.query(Expense).filter(
                Expense.company_id == company_id,
                Expense.date >= month_start,
                Expense.date <= month_end
            ).all()
        )
        expense_data.append(month_expenses / 100000)
        
        # ── NEW: Monthly Net Profit (Revenue - Purchases - Expenses) ─────────
        month_gross_profit = month_revenue - month_purchases
        month_net_profit = month_gross_profit - month_expenses
        profit_trend.append(month_net_profit / 1000)
        profit_labels.append(month_label)
    
    # Status counts for shipments
    all_customer_invoices = cdb.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.invoice_id.like("CUST-%")
    ).all()
    
    status_counts = {
        "delivered": sum(1 for i in all_customer_invoices if i.status == "Paid"),
        "in_transit": sum(1 for i in all_customer_invoices if i.status == "Partial"),
        "pending": sum(1 for i in all_customer_invoices if i.status not in ["Paid", "Partial", "Draft"]),
        "draft": sum(1 for i in all_customer_invoices if i.status == "Draft"),
        "total": len(all_customer_invoices)
    }
    
    # Payment methods breakdown
    cash_txns = cdb.query(CashTransaction).filter_by(company_id=company_id, type='income').all()
    bank_txns = cdb.query(BankTransaction).filter_by(company_id=company_id, type='credit').all()
    
    payment_methods = {
        "Cash": sum(t.amount for t in cash_txns),
        "Online/UPI": sum(t.amount for t in bank_txns if t.transaction_mode == "Online"),
        "Cheque": sum(t.amount for t in bank_txns if t.transaction_mode == "Cheque"),
    }
    
    # Top clients
    clients = cdb.query(Client).filter_by(company_id=company_id).all()
    top_clients_data = []
    for client in clients[:10]:
        client_invoices = cdb.query(Invoice).filter_by(company_id=company_id, client_id=client.id).all()
        client_shipments = [i for i in client_invoices if i.invoice_id.startswith("CUST-")]
        total_billed = sum(float(inv.grand_total or 0) for inv in client_invoices)
        pending = sum(float(getattr(inv, 'balance', 0) or 0) for inv in client_invoices)
        top_clients_data.append({
            "name": client.name,
            "total_billed": total_billed,
            "pending": pending,
            "shipment_count": len(client_shipments)
        })
    top_clients_data.sort(key=lambda x: x["total_billed"], reverse=True)
    top_clients_data = top_clients_data[:5]
    
    # Recent shipments
    recent_shipments = []
    for inv in all_customer_invoices[:10]:
        meta = {}
        if inv.terms:
            try:
                meta = json.loads(inv.terms)
            except:
                pass
        status_label = "Delivered" if inv.status == "Paid" else "In Transit" if inv.status == "Partial" else "Pending" if inv.status != "Draft" else "Draft"
        status_class = "delivered" if inv.status == "Paid" else "transit" if inv.status == "Partial" else "pending"
        recent_shipments.append({
            "docket_no": meta.get("docket_no", inv.invoice_id),
            "customer_name": inv.client_obj.name if inv.client_obj else (inv.contact_person or "—"),
            "destination": meta.get("destination", ""),
            "total": float(inv.grand_total or 0),
            "status": inv.status,
            "status_label": status_label,
            "status_class": status_class
        })
    
    # Recent payments
    recent_payments = []
    for txn in cash_txns[:10]:
        recent_payments.append({
            "date": txn.date.strftime("%d %b %Y"),
            "customer": txn.description[:30],
            "invoice_id": txn.reference or "—",
            "amount": txn.amount,
            "mode": "Cash"
        })
    for txn in bank_txns[:5]:
        recent_payments.append({
            "date": txn.date.strftime("%d %b %Y"),
            "customer": txn.description[:30],
            "invoice_id": txn.reference or "—",
            "amount": txn.amount,
            "mode": txn.transaction_mode or "Bank"
        })
    recent_payments.sort(key=lambda x: x['date'], reverse=True)
    recent_payments = recent_payments[:10]
    
    # Pending invoices
    pending_invoices = []
    for inv in all_invoices:
        balance = float(getattr(inv, 'balance', 0) or 0)
        if balance > 0:
            pending_invoices.append({
                "invoice_id": inv.invoice_id,
                "customer": inv.client_obj.name if inv.client_obj else (inv.contact_person or "—"),
                "date": inv.date.strftime("%d %b %Y") if inv.date else "—",
                "due_date": inv.due_date.strftime("%d %b %Y") if inv.due_date else "—",
                "balance": balance
            })
    pending_invoices = pending_invoices[:10]

    # Recent purchase invoices for the Recent Purchases table
    recent_purchases_raw = cdb.query(PurchaseInvoice).filter_by(
        company_id=company_id
    ).order_by(PurchaseInvoice.date.desc()).limit(10).all()

    recent_purchases_data = []
    for p in recent_purchases_raw:
        try:
            supplier_name = p.supplier.name if p.supplier else (getattr(p, 'supplier_name', None) or "—")
        except Exception:
            supplier_name = getattr(p, 'supplier_name', None) or "—"
        recent_purchases_data.append({
            "id": p.invoice_id,
            "supplier": supplier_name,
            "date": p.date.strftime("%d %b %Y") if p.date else "—",
            "total": float(p.grand_total or 0),
            "status": p.status or "Unpaid"
        })

    expense_categories = {}
    for exp in period_expenses:
        expense_categories[exp.category] = expense_categories.get(exp.category, 0) + exp.amount

    kpi = {
        "cash_balance": cash_balance,
        "bank_balance": bank_balance,
        "total_revenue": total_revenue,
        "total_purchases": total_purchases,
        "total_expenses": total_expenses,           # ── NEW
        "gross_profit": gross_profit,               # ── NEW
        "net_profit": net_profit,
        "pending_amount": pending_amount,
        "cash_inflow_period": cash_inflow_period,
        "cash_outflow_period": cash_outflow_period,
        "cash_net_period": cash_net_period,
    }

    return render_template("dashboard.html",
                         company=company,
                         kpi=kpi,
                         from_date=from_date.strftime('%Y-%m-%d'),
                         to_date=to_date.strftime('%Y-%m-%d'),
                         chart_labels=chart_labels,
                         revenue_data=revenue_data,
                         purchase_data=purchase_data,
                         expense_data=expense_data,  
                         profit_labels=profit_labels,
                         profit_trend=profit_trend,
                         cash_inflow_period=cash_inflow_period,
                         cash_outflow_period=cash_outflow_period,
                         cash_net_period=cash_net_period,
                         top_clients_data=top_clients_data,
                         status_counts=status_counts,
                         payment_methods=payment_methods,
                         recent_shipments=recent_shipments,
                         recent_payments=recent_payments,
                         pending_invoices=pending_invoices,
                         recent_purchases_data=recent_purchases_data,
                         total_shipments=status_counts["total"])


@app.route("/api/dashboard-data")
@login_required
def api_dashboard_data():
    """API endpoint for dashboard data with date filters"""
    cdb = get_cdb()
    company_id = get_current_company()
    
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    
    if not from_date_str:
        from_date = date(2000, 1, 1)
    else:
        from_date = date.fromisoformat(from_date_str)
    
    if not to_date_str:
        to_date = date.today()
    else:
        to_date = date.fromisoformat(to_date_str)
    
    # Cash in Hand
    cash_transactions = cdb.query(CashTransaction).filter_by(company_id=company_id).all()
    cash_balance = sum(t.amount for t in cash_transactions if t.type == 'income') - \
                   sum(t.amount for t in cash_transactions if t.type == 'expense')
    
    # Bank Balance
    bank_accounts = cdb.query(BankAccount).filter_by(company_id=company_id, status='Active').all()
    bank_balance = sum(acc.balance for acc in bank_accounts)
    
    # Filtered Sales Invoices
    sales_invoices = cdb.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.date >= from_date,
        Invoice.date <= to_date
    ).all()
    total_revenue = sum(inv.grand_total or 0 for inv in sales_invoices)
    
    # Filtered Purchase Invoices
    purchase_invoices = cdb.query(PurchaseInvoice).filter(
        PurchaseInvoice.company_id == company_id,
        PurchaseInvoice.date >= from_date,
        PurchaseInvoice.date <= to_date
    ).all()
    total_purchases = sum(pur.grand_total or 0 for pur in purchase_invoices)
    
    # ── NEW: Expenses for period ─────────────────────────────────────────────
    period_expenses = cdb.query(Expense).filter(
        Expense.company_id == company_id,
        Expense.date >= from_date,
        Expense.date <= to_date
    ).all()
    total_expenses = sum(exp.amount or 0 for exp in period_expenses)
    
    gross_profit = total_revenue - total_purchases
    net_profit = gross_profit - total_expenses
    
    all_invoices = cdb.query(Invoice).filter_by(company_id=company_id).all()
    pending_amount = sum(getattr(inv, 'balance', 0) or 0 for inv in all_invoices)
    
    period_cash_income = cdb.query(CashTransaction).filter(
        CashTransaction.company_id == company_id,
        CashTransaction.type == 'income',
        CashTransaction.date >= from_date,
        CashTransaction.date <= to_date
    ).all()
    period_cash_expense = cdb.query(CashTransaction).filter(
        CashTransaction.company_id == company_id,
        CashTransaction.type == 'expense',
        CashTransaction.date >= from_date,
        CashTransaction.date <= to_date
    ).all()
    cash_inflow_period = sum(t.amount for t in period_cash_income)
    cash_outflow_period = sum(t.amount for t in period_cash_expense)
    
    # Chart data (last 6 months)
    chart_labels = []
    revenue_data = []
    purchase_data = []
    expense_data = []  # ── NEW
    profit_trend = []
    profit_labels = []
    
    for i in range(5, -1, -1):
        month_date = date.today().replace(day=1) - timedelta(days=30 * i)
        month_start = month_date.replace(day=1)
        if month_date.month == 12:
            month_end = month_date.replace(day=31)
        else:
            month_end = month_date.replace(month=month_date.month + 1, day=1) - timedelta(days=1)
        
        month_label = month_date.strftime('%b %Y')
        chart_labels.append(month_label)
        
        month_revenue = sum(
            inv.grand_total or 0 for inv in cdb.query(Invoice).filter(
                Invoice.company_id == company_id,
                Invoice.date >= month_start,
                Invoice.date <= month_end
            ).all()
        )
        revenue_data.append(month_revenue / 100000)
        
        month_purchases = sum(
            pur.grand_total or 0 for pur in cdb.query(PurchaseInvoice).filter(
                PurchaseInvoice.company_id == company_id,
                PurchaseInvoice.date >= month_start,
                PurchaseInvoice.date <= month_end
            ).all()
        )
        purchase_data.append(month_purchases / 100000)
        
        # ── NEW: Monthly Expenses ──────────────────────────────────────────────
        month_expenses = sum(
            exp.amount or 0 for exp in cdb.query(Expense).filter(
                Expense.company_id == company_id,
                Expense.date >= month_start,
                Expense.date <= month_end
            ).all()
        )
        expense_data.append(month_expenses / 100000)
        
        if i <= 5:
            profit_labels.append(month_label)
            month_net_profit = (month_revenue - month_purchases) - month_expenses
            profit_trend.append(month_net_profit / 1000)
    
    # Top clients
    clients = cdb.query(Client).filter_by(company_id=company_id).all()
    top_clients_data = []
    for client in clients[:10]:
        client_invoices = cdb.query(Invoice).filter_by(company_id=company_id, client_id=client.id).all()
        total_billed = sum(inv.grand_total or 0 for inv in client_invoices)
        pending = sum(getattr(inv, 'balance', 0) or 0 for inv in client_invoices)
        top_clients_data.append({
            "name": client.name,
            "total_billed": total_billed,
            "pending": pending,
            "status": client.status or "Active"
        })
    top_clients_data.sort(key=lambda x: x["total_billed"], reverse=True)
    top_clients_data = top_clients_data[:5]
    
    # Recent invoices
    recent_invoices_raw = cdb.query(Invoice).filter_by(company_id=company_id).order_by(Invoice.date.desc()).limit(10).all()
    recent_invoices_data = []
    for inv in recent_invoices_raw:
        client_name = inv.client_obj.name if inv.client_obj else (inv.contact_person or "—")
        total = inv.grand_total or 0
        balance = getattr(inv, 'balance', 0) or 0
        if balance <= 0:
            status = "Paid"
        elif inv.status == "Partial":
            status = "Partial"
        else:
            status = "Pending"
        recent_invoices_data.append({
            "id": inv.invoice_id,
            "customer": client_name,
            "date": inv.date.strftime("%d %b %Y") if inv.date else "—",
            "total": total,
            "status": status
        })
    
    # Low stock
    stock_items = cdb.query(StockItem).filter_by(company_id=company_id).all()
    low_stock_items = []
    for item in stock_items:
        reorder = item.reorder_level or 10
        if item.quantity <= reorder and item.quantity > 0:
            low_stock_items.append({
                "code": item.code,
                "name": item.name,
                "quantity": item.quantity,
                "reorder_level": reorder
            })
    low_stock_items = low_stock_items[:8]
    
    return jsonify({
        "kpi": {
            "cash_balance": cash_balance,
            "bank_balance": bank_balance,
            "total_revenue": total_revenue,
            "total_purchases": total_purchases,
            "total_expenses": total_expenses,        # ── NEW
            "gross_profit": gross_profit,            # ── NEW
            "net_profit": net_profit,                # ── NEW
            "pending_amount": pending_amount,
            "cash_inflow_period": cash_inflow_period,
            "cash_outflow_period": cash_outflow_period,
            "cash_net_period": cash_inflow_period - cash_outflow_period,
        },
        "chart_labels": chart_labels,
        "revenue_data": revenue_data,
        "purchase_data": purchase_data,
        "expense_data": expense_data,                # ── NEW
        "profit_labels": profit_labels,
        "profit_trend": profit_trend,
        "top_clients": top_clients_data,
        "recent_invoices": recent_invoices_data,
        "low_stock": low_stock_items,
    })


# ── Price List Routes ─────────────────────────────────────────────────────────

@app.route("/price-lists")
@login_required
def price_lists():
    """Manage price lists"""
    cdb = get_cdb()
    company_id = get_current_company()
    price_lists = cdb.query(PriceList).filter_by(company_id=company_id, is_active=True).all()
    return render_template("price_lists.html", price_lists=price_lists, active='price_lists')

@app.route("/debug/price-lists-data")
@login_required
def debug_price_lists_data():
    """Debug endpoint to check price list data in database"""
    cdb = get_cdb()
    company_id = get_current_company()
    
    price_lists = cdb.query(PriceList).filter_by(company_id=company_id).all()
    
    result = []
    for pl in price_lists:
        try:
            data = json.loads(pl.rate_data) if pl.rate_data else {}
            result.append({
                'id': pl.id,
                'courier': pl.courier,
                'filename': pl.filename,
                'is_active': pl.is_active,
                'countries': list(data.get('countries', {}).keys())[:5] if data.get('countries') else [],
                'weights': data.get('weights', []),
                'has_data': bool(data.get('countries'))
            })
        except Exception as e:
            result.append({
                'id': pl.id,
                'courier': pl.courier,
                'filename': pl.filename,
                'is_active': pl.is_active,
                'error': str(e)
            })
    
    return jsonify({
        'total': len(price_lists),
        'lists': result
    })

@app.route("/debug/excel-columns", methods=["POST"])
@login_required
def debug_excel_columns():
    """Debug endpoint to check Excel file columns"""
    if 'price_file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['price_file']
    try:
        df = pd.read_excel(file, engine='openpyxl')
        columns = df.columns.tolist()
        first_row = df.iloc[0].to_dict() if len(df) > 0 else {}
        
        return jsonify({
            'columns': columns,
            'first_row': {str(k): str(v) for k, v in first_row.items()},
            'row_count': len(df)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route("/price-lists/upload", methods=["GET", "POST"])
@login_required
def upload_price_list():
    """Upload a price list Excel file"""
    cdb = get_cdb()
    company_id = get_current_company()
    
    if request.method == "POST":
        print("=" * 80)
        print("UPLOAD ROUTE EXECUTED")
        print("=" * 80)
        if 'price_file' not in request.files:
            flash("No file uploaded", "error")
            return redirect(url_for("price_lists"))
        
        file = request.files['price_file']
        courier = request.form.get('courier', '').strip().upper()
        print("File object:", file)
        print("Filename:", repr(file.filename))
        print("Courier:", repr(courier))
        print("Allowed:", allowed_file(file.filename) if file.filename else False)
        
        if not courier:
            flash("Courier name is required", "error")
            return redirect(url_for("price_lists"))
        
        print("Entering upload block...")

        if file is None:
            print("File is None")

        elif file.filename == "":
            print("Filename is empty")

        elif not allowed_file(file.filename):
            print("Extension not allowed:", file.filename)

        else:
            print("Everything OK")
            try:
                # Save the file first
                filename = secure_filename(f"{courier}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                filepath = os.path.join('uploads/price_lists', filename)
                os.makedirs('uploads/price_lists', exist_ok=True)
                file.save(filepath)
                
                # Read the saved file
                df = pd.read_excel(filepath, engine='openpyxl')
                
                print(f"📊 File: {file.filename}")
                print(f"📊 Columns: {df.columns.tolist()}")
                print(f"📊 Rows: {len(df)}")
                
                if len(df) == 0:
                    flash("The Excel file is empty", "error")
                    return redirect(url_for("price_lists"))
                
                # Parse rates based on format
                rate_data = parse_price_list(df, courier)
                
                # Check if we parsed any data
                if not rate_data['countries']:
                    flash(f"No countries parsed from {file.filename}. Columns found: {df.columns.tolist()}", "error")
                    return redirect(url_for("price_lists"))
                
                # Deactivate old price lists for this courier
                old_lists = cdb.query(PriceList).filter_by(company_id=company_id, courier=courier).all()
                for old in old_lists:
                    old.is_active = False
                
                # Save new price list
                price_list = PriceList(
                    company_id=company_id,
                    courier=courier,
                    filename=file.filename,
                    file_path=filepath,
                    rate_data=json.dumps(rate_data),
                    is_active=True,
                    uploaded_by=get_current_user().get('email')
                )
                cdb.add(price_list)
                cdb.commit()
                
                flash(f"✅ Price list for {courier} uploaded! {len(rate_data['countries'])} countries, {len(rate_data['weights'])} weight tiers.", "success")
                
            except Exception as e:
                flash(f"Error processing file: {str(e)}", "error")
                print(f"Upload error: {e}")
                import traceback
                traceback.print_exc()
        
        return redirect(url_for("price_lists"))
    
    return render_template("upload_price_list.html", active='price_lists')


@app.route("/api/rate-lookup")
@login_required
def api_rate_lookup():
    """API endpoint to lookup shipping rate"""
    cdb = get_cdb()
    company_id = get_current_company()
    
    courier = request.args.get('courier', '').strip().upper()
    destination = request.args.get('destination', '').strip().upper()
    weight = float(request.args.get('weight', 0))
    
    print("=" * 60)
    print(f"🔍 RATE LOOKUP REQUEST:")
    print(f"   Courier: {courier}")
    print(f"   Destination: {destination}")
    print(f"   Weight: {weight}")
    print("=" * 60)
    
    if not courier or not destination or weight <= 0:
        return jsonify({'error': 'Missing parameters'}), 400
    
    # Get active price list for this courier
    price_list = cdb.query(PriceList).filter_by(
        company_id=company_id,
        courier=courier,
        is_active=True
    ).first()
    
    print(f"📋 Price list found: {price_list is not None}")
    
    if not price_list:
        return jsonify({'error': f'No active price list found for {courier}'}), 404
    
    try:
        rate_data = json.loads(price_list.rate_data)
        print(f"📊 Rate data loaded: {len(rate_data.get('countries', {}))} countries")
        
        countries = rate_data.get('countries', {})
        weights = sorted(rate_data.get('weights', []))
        
        print(f"📍 Available countries: {list(countries.keys())[:5]}...")
        print(f"⚖️ Available weights: {weights}")
        
        # Find matching country
        matched_country = None
        matched_rates = None
        
        # 1. Try exact match
        if destination in countries:
            matched_country = destination
            matched_rates = countries[destination]
            print(f"✅ Exact match: {matched_country}")
        
        # 2. Try partial match (destination contains country or vice versa)
        if not matched_rates:
            for country, rates in countries.items():
                if destination in country or country in destination:
                    matched_country = country
                    matched_rates = rates
                    print(f"✅ Partial match: {matched_country}")
                    break
        
        # 3. Try word matching (split by spaces)
        if not matched_rates:
            dest_words = destination.split()
            for country, rates in countries.items():
                country_words = country.split()
                for dw in dest_words:
                    if len(dw) > 2:
                        for cw in country_words:
                            if dw in cw or cw in dw:
                                matched_country = country
                                matched_rates = rates
                                print(f"✅ Word match: {matched_country}")
                                break
                    if matched_rates:
                        break
                if matched_rates:
                    break
        
        if not matched_rates:
            print(f"❌ No match found for: {destination}")
            return jsonify({'error': f'No rate found for {destination}. Available countries: {", ".join(list(countries.keys())[:10])}'}), 404
        
        # Find closest weight
        # IMPORTANT: Convert rate keys to float for comparison
        rate_keys = [float(k) for k in matched_rates.keys()]
        rate_keys.sort()
        
        print(f"🔑 Rate keys for {matched_country}: {rate_keys}")
        
        closest_weight = rate_keys[0] if rate_keys else weight
        for w in rate_keys:
            if w >= weight:
                closest_weight = w
                break
            closest_weight = w
        
        # Get the rate - try both float and string key
        rate = matched_rates.get(closest_weight, 0)
        
        # If not found, try string version
        if rate == 0:
            rate = matched_rates.get(str(closest_weight), 0)
        
        print(f"💰 Rate: {rate} for {closest_weight}kg")
        
        if rate <= 0:
            return jsonify({'error': f'No rate for {closest_weight}kg in {matched_country}. Available weights: {rate_keys}'}), 404
        
        # Log lookup
        try:
            lookup = RateLookup(
                company_id=company_id,
                courier=courier,
                destination=destination,
                weight=weight,
                rate=rate
            )
            cdb.add(lookup)
            cdb.commit()
        except Exception as e:
            print(f"⚠️ Could not log lookup: {e}")
        
        return jsonify({
            'success': True,
            'rate': rate,
            'weight_used': closest_weight,
            'country_matched': matched_country,
            'courier': courier,
            'destination': destination
        })
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/price-lists/list")
@login_required
def api_price_lists_list():
    """Return list of available couriers with price lists"""
    cdb = get_cdb()
    company_id = get_current_company()
    
    price_lists = cdb.query(PriceList).filter_by(company_id=company_id, is_active=True).all()
    
    return jsonify([{
        'courier': pl.courier,
        'filename': pl.filename,
        'uploaded_at': pl.uploaded_at.strftime('%d %b %Y'),
        'countries': len(json.loads(pl.rate_data).get('countries', {}))
    } for pl in price_lists])

# ─────────────────────────────────────────────────────────────────────────────
# ── Orders ────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/orders")
@login_required
def order_list():
    cdb = get_cdb()
    company_id    = get_current_company()
    filter_status = request.args.get("status", "All")
    query         = cdb.query(Order).filter_by(company_id=company_id)
    if filter_status != "All":
        query = query.filter_by(status=filter_status)
    orders  = query.order_by(Order.date.desc()).all()
    clients = cdb.query(Client).filter(
        Client.company_id == company_id,
        ~Client.client_type.in_(["Supplier", "Both"])
    ).all()
    return render_template("orders.html", orders=orders, clients=clients,
                           current_status=filter_status)


@app.route("/orders/add", methods=["GET", "POST"])
@login_required
def order_add():
    cdb = get_cdb()
    company_id = get_current_company()
    clients = cdb.query(Client).filter(
        Client.company_id == company_id,
        ~Client.client_type.in_(["Supplier", "Both"])
    ).all()

    if request.method == "POST":
        client_id   = request.form.get("client_id")
        amount      = float(request.form.get("amount", 0))
        received    = float(request.form.get("received", 0))
        status      = request.form.get("status", "Pending")
        order_date  = request.form.get("order_date") or str(date.today())
        ord_count   = cdb.query(Order).count()
        new_order   = Order(
            order_id=f"ORD-{datetime.now().strftime('%Y%m%d')}-{ord_count+1:03d}",
            company_id=company_id,
            client_id=int(client_id) if client_id else None,
            employee_id=get_current_user().get("user_id"),
            date=date.fromisoformat(order_date),
            amount=amount, received=received, status=status,
        )
        cdb.add(new_order)
        cdb.commit()
        flash("Order created successfully!")
        return redirect(url_for("order_list"))

    return render_template("order_form.html", clients=clients)


@app.route("/orders/edit/<int:order_pk>", methods=["GET", "POST"])
@login_required
def order_edit(order_pk):
    cdb = get_cdb()
    company_id = get_current_company()
    order      = _first_or_404(cdb.query(Order).filter_by(id=order_pk, company_id=company_id).first())
    clients = cdb.query(Client).filter(
        Client.company_id == company_id,
        ~Client.client_type.in_(["Supplier", "Both"])
    ).all()

    if request.method == "POST":
        order.client_id = int(request.form.get("client_id")) if request.form.get("client_id") else None
        order.amount    = float(request.form.get("amount", 0))
        order.received  = float(request.form.get("received", 0))
        order.status    = request.form.get("status", "Pending")
        cdb.commit()
        flash("Order updated!")
        return redirect(url_for("order_list"))

    return render_template("order_form.html", order=order, clients=clients)


@app.route("/orders/delete/<int:order_pk>", methods=["POST"])
@login_required
def order_delete(order_pk):
    cdb = get_cdb()
    company_id = get_current_company()
    order      = _first_or_404(cdb.query(Order).filter_by(id=order_pk, company_id=company_id).first())
    cdb.delete(order)
    cdb.commit()
    flash("Order deleted.")
    return redirect(url_for("order_list"))


# ─────────────────────────────────────────────────────────────────────────────
# ── Clients ───────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_client(c):
    """Return a dict whose keys match what clients.html / client_form.html expect."""
    return {
        # identity
        "id":              c.id,
        "client_name":     c.name,
        "client_type":     c.client_type     or "Business",
        "contact_person":  c.contact_person  or "",
        # contact
        "phone":           c.phone           or "",
        "alternate_phone": c.alternate_phone or "",
        "email":           c.email           or "",
        "website":         c.website         or "",
        # address
        "address_line1":   c.address_line1   or "",
        "address_line2":   c.address_line2   or "",
        "city":            c.city            or "",
        "state":           c.state           or "",
        "pincode":         c.pincode         or "",
        "country":         c.country         or "India",
        # GST & tax
        "gst_number":      c.gst_number      or "",
        "pan_number":      c.pan_number      or "",
        "gst_type":        c.gst_type        or "Regular",
        # financial
        "credit_limit":    c.credit_limit    or 0.0,
        "credit_days":     c.credit_days     or 30,
        "outstanding":     c.pending         or 0.0,
        "opening_balance": c.opening_balance or 0.0,
        "last_payment":    c.last_payment,
        # status
        "status":          c.status          or "Active",
        "notes":           c.notes           or "",
        "created_at":      c.created_at,
    }


@app.route("/clients")
@login_required
def client_list():
    cdb = get_cdb()
    company_id    = get_current_company()
    filter_status = request.args.get("status", "All")

    query = cdb.query(Client).filter(
        Client.company_id == company_id,
        Client.client_type.in_(["Customer", "Business", "Individual"])
    )
    if filter_status != "All":
        query = query.filter_by(status=filter_status)

    clients = [_normalize_client(c) for c in query.all()]
    return render_template("clients.html", clients=clients, current_status=filter_status)


# /clients/new  ── template links here for new client
@app.route("/clients/new", methods=["GET", "POST"])
@login_required
def client_new():
    cdb = get_cdb()
    company_id = get_current_company()
    if request.method == "POST":
        f = request.form

        # GST uniqueness check (per company)
        gst = f.get("gst_number", "").strip().upper()
        if gst:
            existing_gst = cdb.query(Client).filter_by(
                company_id=company_id, gst_number=gst
            ).first()
            if existing_gst:
                flash(f"GST number {gst} is already registered to client '{existing_gst.name}'. Please check and try again.", "error")
                return render_template("client_form.html", form_data=f)

        new_client = Client(
            company_id      = company_id,
            name            = f.get("client_name", "").strip(),
            client_type     = f.get("client_type", "Business"),
            contact_person  = f.get("contact_person", "").strip(),
            phone           = f.get("phone", "").strip(),
            alternate_phone = f.get("alternate_phone", "").strip(),
            email           = f.get("email", "").strip().lower(),
            website         = f.get("website", "").strip(),
            address_line1   = f.get("address_line1", "").strip(),
            address_line2   = f.get("address_line2", "").strip(),
            city            = f.get("city", "").strip(),
            state           = f.get("state", "").strip(),
            pincode         = f.get("pincode", "").strip(),
            country         = f.get("country", "India").strip(),
            gst_number      = gst or None,
            pan_number      = f.get("pan_number", "").strip().upper() or None,
            gst_type        = f.get("gst_type", "Regular"),
            credit_limit    = float(f.get("credit_limit", 0) or 0),
            credit_days     = int(f.get("credit_days", 30) or 30),
            pending         = float(f.get("opening_balance", 0) or 0),
            opening_balance = float(f.get("opening_balance", 0) or 0),
            status          = f.get("status", "Active"),
            notes           = f.get("notes", "").strip(),
            created_at      = date.today(),
        )
        cdb.add(new_client)
        cdb.commit()
        flash(f"Client '{new_client.name}' added successfully!")
        return redirect(url_for("client_list"))
    return render_template("client_form.html", form_data={})


# Keep /clients/add as an alias so old links still work
@app.route("/clients/add", methods=["GET", "POST"])
@login_required
def client_add():
    return client_new()


# /clients/<id>  ── view detail (template links here with 👁️)
@app.route("/clients/<int:client_pk>")
@login_required
def client_view(client_pk):
    cdb = get_cdb()
    company_id = get_current_company()
    c = _first_or_404(cdb.query(Client).filter_by(id=client_pk, company_id=company_id).first())
    client = _normalize_client(c)
    invoices = cdb.query(Invoice).filter_by(company_id=company_id, client_id=c.id).order_by(Invoice.date.desc()).all()
    orders   = cdb.query(Order).filter_by(company_id=company_id, client_id=c.id).order_by(Order.date.desc()).all()
    return render_template("client_detail.html", client=client, invoices=invoices, orders=orders)


# /clients/<id>/edit
@app.route("/clients/<int:client_pk>/edit", methods=["GET", "POST"])
@login_required
def client_edit(client_pk):
    cdb = get_cdb()
    company_id = get_current_company()
    c          = _first_or_404(cdb.query(Client).filter_by(id=client_pk, company_id=company_id).first())
    if request.method == "POST":
        f   = request.form
        gst = f.get("gst_number", "").strip().upper()

        # GST uniqueness: check no OTHER client has the same GST
        if gst:
            existing_gst = cdb.query(Client).filter(
                Client.company_id == company_id,
                Client.gst_number == gst,
                Client.id != c.id
            ).first()
            if existing_gst:
                flash(f"GST number {gst} is already registered to client '{existing_gst.name}'.", "error")
                return render_template("client_form.html", client=_normalize_client(c), form_data=f)

        c.name            = f.get("client_name", c.name).strip()
        c.client_type     = f.get("client_type",     c.client_type)
        c.contact_person  = f.get("contact_person",  c.contact_person or "").strip()
        c.phone           = f.get("phone",            c.phone or "").strip()
        c.alternate_phone = f.get("alternate_phone",  c.alternate_phone or "").strip()
        c.email           = f.get("email",            c.email or "").strip().lower()
        c.website         = f.get("website",          c.website or "").strip()
        c.address_line1   = f.get("address_line1",    c.address_line1 or "").strip()
        c.address_line2   = f.get("address_line2",    c.address_line2 or "").strip()
        c.city            = f.get("city",             c.city or "").strip()
        c.state           = f.get("state",            c.state or "").strip()
        c.pincode         = f.get("pincode",          c.pincode or "").strip()
        c.country         = f.get("country",          c.country or "India").strip()
        c.gst_number      = gst or None
        c.pan_number      = f.get("pan_number",  c.pan_number or "").strip().upper() or None
        c.gst_type        = f.get("gst_type",    c.gst_type)
        c.credit_limit    = float(f.get("credit_limit",    c.credit_limit    or 0) or 0)
        c.credit_days     = int(f.get("credit_days",       c.credit_days     or 30) or 30)
        c.opening_balance = float(f.get("opening_balance", c.opening_balance or 0) or 0)
        c.status          = f.get("status", c.status)
        c.notes           = f.get("notes",   c.notes or "").strip()
        cdb.commit()
        flash(f"Client '{c.name}' updated successfully!")
        return redirect(url_for("client_list"))
    return render_template("client_form.html", client=_normalize_client(c), form_data={})


# /clients/<id>/delete  ── template uses GET link with confirm dialog
@app.route("/clients/<int:client_pk>/delete", methods=["GET", "POST"])
@login_required
def client_delete(client_pk):
    cdb = get_cdb()
    company_id = get_current_company()
    c          = _first_or_404(cdb.query(Client).filter_by(id=client_pk, company_id=company_id).first())
    cdb.delete(c)
    cdb.commit()
    flash("Client deleted.")
    return redirect(url_for("client_list"))


# ─────────────────────────────────────────────────────────────────────────────
# ── Stock / Inventory ─────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
"""@app.route("/inventory")
@login_required
def inventory_list():
    cdb = get_cdb()
    company_id  = get_current_company()
    stock_items = cdb.query(StockItem).filter_by(company_id=company_id).all()

    total_items = len(stock_items)
    in_stock    = sum(1 for i in stock_items if i.quantity > (i.reorder_level or 0))
    low_stock   = sum(1 for i in stock_items if 0 < i.quantity <= (i.reorder_level or 10))
    out_stock   = sum(1 for i in stock_items if i.quantity <= 0)

    stock_summary = {
        "total_items": total_items,
        "in_stock":    in_stock,
        "low_stock":   low_stock,
        "out_stock":   out_stock,
    }

    return render_template("inventory.html",
                           stock_items=stock_items,
                           stock_summary=stock_summary)"""

"""@app.route("/inventory")
@login_required
def inventory_list():
    
    cdb = get_cdb()
    company_id = get_current_company()
    
    # Get all customer invoices (shipments)
    shipments_query = cdb.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.invoice_id.like("CUST-%")
    ).order_by(Invoice.date.desc())
    
    shipments = []
    delivered_count = 0
    in_transit_count = 0
    pending_count = 0
    
    for inv in shipments_query.all():
        # Parse shipment metadata from terms
        meta = {}
        if inv.terms:
            try:
                meta = json.loads(inv.terms)
            except:
                pass
        
        # Extract packages data
        packages = meta.get("packages", [])
        
        # Extract items from invoice items (if any)
        items = []
        total_qty = 0
        total_weight = 0
        
        for pkg in packages:
            total_qty += pkg.get("qty", 1)
            total_weight += (pkg.get("weight", 0) or 0) * pkg.get("qty", 1)
        
        # Also check invoice items
        for item in inv.items:
            items.append({
                "desc": item.description,
                "qty": item.qty,
                "rate": item.rate
            })
            if not total_qty:
                total_qty += item.qty or 0
        
        # Determine status for KPI
        status = inv.status or "Draft"
        if status == "Paid":
            delivered_count += 1
        elif status == "Partial":
            in_transit_count += 1
        elif status == "Draft":
            pending_count += 1
        else:
            pending_count += 1
        
        shipments.append({
            "invoice_id": inv.invoice_id,
            "docket_no": meta.get("docket_no", ""),
            "customer_name": inv.client_obj.name if inv.client_obj else (inv.contact_person or "—"),
            "customer_phone": inv.client_obj.phone if inv.client_obj else (inv.phone or ""),
            "booking_date": inv.date.strftime("%d %b %Y") if inv.date else "—",
            "origin": meta.get("origin", "India"),
            "destination": meta.get("destination", ""),
            "receiver_name": meta.get("receiver_name", ""),
            "receiver_phone": meta.get("receiver_phone", ""),
            "shipment_type": meta.get("shipment_type", "Standard"),
            "mode": meta.get("mode", ""),
            "carrier": meta.get("carrier", ""),
            "status": inv.status or "Draft",
            "total": float(inv.grand_total or 0),
            "packages": packages,
            "items": items,
            "total_qty": total_qty,
            "total_weight": total_weight,
            "weight": meta.get("weight", "0")
        })
    
    return render_template("inventory.html",
                         shipments=shipments,
                         total_shipments=len(shipments),
                         delivered_count=delivered_count,
                         in_transit_count=in_transit_count,
                         pending_count=pending_count)


@app.route("/inventory")
@login_required
def inventory_list():
    
    cdb = get_cdb()
    company_id = get_current_company()
    
    # Get all customer invoices (shipments)
    shipments_query = cdb.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.invoice_id.like("CUST-%")
    ).order_by(Invoice.date.desc())
    
    shipments = []
    delivered_count = 0
    in_transit_count = 0
    pending_count = 0
    draft_count = 0
    
    for inv in shipments_query.all():
        # Parse shipment metadata from terms
        meta = {}
        if inv.terms:
            try:
                meta = json.loads(inv.terms)
            except:
                pass
        
        # Extract packages data
        packages = meta.get("packages", [])
        
        # Extract items from invoice items (if any)
        items = []
        total_qty = 0
        total_weight = 0
        
        for pkg in packages:
            total_qty += pkg.get("qty", 1)
            total_weight += (pkg.get("weight", 0) or 0) * pkg.get("qty", 1)
        
        # Also check invoice items
        for item in inv.items:
            items.append({
                "desc": item.description,
                "qty": item.qty,
                "rate": item.rate
            })
            if not total_qty:
                total_qty += item.qty or 0
        
        # Determine status for KPI
        status = inv.status or "Draft"
        if status == "Paid":
            delivered_count += 1
        elif status == "Partial":
            in_transit_count += 1
        elif status == "Draft":
            draft_count += 1
        else:
            pending_count += 1
        
        shipments.append({
            "invoice_id": inv.invoice_id,
            "docket_no": meta.get("docket_no", inv.invoice_id),
            "customer_name": inv.client_obj.name if inv.client_obj else (inv.contact_person or "—"),
            "customer_phone": inv.client_obj.phone if inv.client_obj else (inv.phone or ""),
            "booking_date": inv.date.strftime("%d %b %Y") if inv.date else "—",
            "origin": meta.get("origin", "India"),
            "destination": meta.get("destination", ""),
            "receiver_name": meta.get("receiver_name", ""),
            "receiver_phone": meta.get("receiver_phone", ""),
            "shipment_type": meta.get("shipment_type", "Standard"),
            "mode": meta.get("mode", ""),
            "carrier": meta.get("carrier", ""),
            "status": inv.status or "Draft",
            "total": float(inv.grand_total or 0),
            "packages": packages,
            "items": items,
            "total_qty": total_qty,
            "total_weight": total_weight,
            "weight": meta.get("weight", "0")
        })
    
    # ── Inventory totals by package type ─────────────────────────────────────
    # read actual remaining stock from StockItem table
    stock_items = cdb.query(StockItem).filter_by(company_id=company_id).all()

    inventory_by_type = {}
    total_inventory   = 0
    for item in stock_items:
        qty = int(item.quantity or 0)
        if qty <= 0:
            continue
        # Normalize name to match template type_icons keys
        name = (item.name or "Other").strip()
        inventory_by_type[name] = inventory_by_type.get(name, 0) + qty
        total_inventory += qty

    return render_template("inventory.html",
                         shipments=shipments,
                         total_shipments=len(shipments),
                         delivered_count=delivered_count,
                         in_transit_count=in_transit_count,
                         pending_count=pending_count,
                         draft_count=draft_count,
                         total_inventory=total_inventory,
                         inventory_by_type=inventory_by_type)"""

@app.route("/inventory")
@login_required
def inventory_list():
    cdb = get_customer_session(get_current_company())
    company_id = get_current_company()

    stock_items = cdb.query(StockItem).filter_by(company_id=company_id).all()

    # ── Top summary: total + by item_type ────────────────────────────────────
    total_inventory  = 0
    inventory_by_type = {}   # {"Box": 455, "Envelope": 3000, ...}

    for item in stock_items:
        qty = int(item.quantity or 0)
        if qty <= 0:
            continue
        total_inventory += qty
        itype = (item.item_type or item.category or "Other").strip()
        inventory_by_type[itype] = inventory_by_type.get(itype, 0) + qty

    # ── Party-wise breakdown ──────────────────────────────────────────────────
    # Build: {client_id: {"name": str, "items": {item_type: qty}}}
    client_ids = set(i.client_id for i in stock_items if i.client_id)
    clients    = {
        c.id: c.name
        for c in cdb.query(Client).filter(
            Client.id.in_(client_ids),
            Client.company_id == company_id
        ).all()
    } if client_ids else {}

    # All item types that appear across any party — for table columns
    all_types = sorted(set(
        (i.item_type or i.category or "Other").strip()
        for i in stock_items if i.client_id
    ))

    party_stock = {}   # {client_name: {item_type: qty}}
    for item in stock_items:
        if not item.client_id:
            continue
        qty = int(item.quantity or 0)
        if qty <= 0:
            continue
        cname = clients.get(item.client_id, f"Party #{item.client_id}")
        itype = (item.item_type or item.category or "Other").strip()
        if cname not in party_stock:
            party_stock[cname] = {}
        party_stock[cname][itype] = party_stock[cname].get(itype, 0) + qty

    return render_template("inventory.html",
        total_inventory=total_inventory,
        inventory_by_type=inventory_by_type,
        party_stock=party_stock,
        all_types=all_types,
    )

# ── Stock JSON API (used by inventory.html JS modals) ────────────────────────
@app.route("/stock/item/<code>")
@login_required
def stock_item_get(code):
    cdb = get_cdb()
    company_id = get_current_company()
    item = _first_or_404(cdb.query(StockItem).filter_by(company_id=company_id, code=code.upper()).first())
    return jsonify({
        "code":          item.code,
        "name":          item.name,
        "category":      item.category or "",
        "quantity":      item.quantity,
        "unit":          item.unit or "pcs",
        "unit_price":    item.unit_price,
        "reorder_level": item.reorder_level or 10,
        "hsn":           item.hsn or "",
    })

@app.route("/api/stock/items")
@login_required
def api_stock_items():
    cdb = get_cdb()
    
    company_id = get_current_company()
    items = cdb.query(StockItem).filter_by(company_id=company_id).order_by(StockItem.name).all()
    return jsonify([{
        "id":            item.id,
        "code":          item.code or "",
        "name":          item.name,
        "unit":          item.unit or "pcs",
        "quantity":      item.quantity,
        "unit_price":    float(item.unit_price or 0),
        "purchase_rate": float(item.purchase_rate or item.last_purchase_rate or 0),
        "gst_percent":   float(item.gst_percent or 18),
        "hsn":           item.hsn or "",
        "category":      item.category or "",
        "reorder_level": item.reorder_level or 10,
    } for item in items])

@app.route("/stock/save", methods=["POST"])
@login_required
def stock_save():
    """Create or update a stock item via JSON (called from the modal form)."""
    cdb = get_cdb()
    company_id = get_current_company()
    data       = request.get_json(force=True)

    code = data.get("code", "").strip().upper()
    item = cdb.query(StockItem).filter_by(company_id=company_id, code=code).first() if code else None

    if item:
        # update existing
        item.name          = data.get("name", item.name)
        item.category      = data.get("category", item.category)
        item.quantity      = float(data.get("quantity", item.quantity))
        item.unit          = data.get("unit", item.unit)
        item.unit_price    = float(data.get("unit_price", item.unit_price))
        item.reorder_level = float(data.get("reorder_level", item.reorder_level))
        item.last_updated  = date.today()
    else:
        # auto-generate a code if none provided
        if not code:
            count = cdb.query(StockItem).filter_by(company_id=company_id).count()
            code  = f"PROD{count + 1:03d}"
        item = StockItem(
            company_id    = company_id,
            code          = code,
            name          = data.get("name", ""),
            category      = data.get("category", "Other"),
            quantity      = float(data.get("quantity", 0)),
            unit          = data.get("unit", "pcs"),
            unit_price    = float(data.get("unit_price", 0)),
            reorder_level = float(data.get("reorder_level", 10)),
            hsn           = data.get("hsn", ""),
            last_updated  = date.today(),
        )
        cdb.add(item)

    cdb.commit()
    return jsonify({"success": True, "code": item.code})


@app.route("/stock/adjust", methods=["POST"])
@login_required
def stock_adjust():
    """Quick quantity adjustment from the Adj button in the table."""
    cdb = get_cdb()
    company_id = get_current_company()
    data       = request.get_json(force=True)
    code       = data.get("code", "").strip().upper()
    item       = _first_or_404(cdb.query(StockItem).filter_by(company_id=company_id, code=code).first())
    item.quantity     = float(data.get("quantity", item.quantity))
    item.last_updated = date.today()
    cdb.commit()
    return jsonify({"success": True})


@app.route("/stock/movements/<code>")
@login_required
def stock_movements(code):
    """Return full movement history for a stock item (purchases IN, invoices OUT)."""
    cdb = get_cdb()
    company_id = get_current_company()
    item = cdb.query(StockItem).filter_by(
        company_id=company_id, code=code.upper()
    ).first()

    history = (
        cdb.query(StockPurchaseHistory)
        .filter_by(stock_item_id=item.id)
        .order_by(StockPurchaseHistory.purchase_date.desc())
        .all()
    )

    movements = []
    total_in  = 0
    total_out = 0

    for h in history:
        qty = h.quantity or 0
        is_in = qty > 0

        # Determine movement type and reference
        if h.purchase_invoice_id:
            inv = cdb.get(PurchaseInvoice, h.purchase_invoice_id)
            ref  = inv.invoice_number or inv.invoice_id if inv else f"PUR-{h.purchase_invoice_id}"
            mtype = "Purchase"
        else:
            # Negative qty = dispatched via customer invoice
            mtype = "Dispatched"
            ref   = "Customer Invoice"

        if is_in:
            total_in += abs(qty)
        else:
            total_out += abs(qty)

        movements.append({
            "date":     h.purchase_date.strftime("%d %b %Y") if h.purchase_date else "",
            "type":     mtype,
            "ref":      ref,
            "quantity": qty,
            "rate":     float(h.purchase_rate or 0),
        })

    return jsonify({
        "code":       item.code,
        "name":       item.name,
        "movements":  movements,
        "total_in":   total_in,
        "total_out":  total_out,
    })



@login_required
def inventory_add():
    company_id = get_current_company()
    if request.method == "POST":
        item = StockItem(
            company_id=company_id,
            code=request.form.get("code", "").upper(),
            name=request.form.get("name", ""),
            category=request.form.get("category", ""),
            quantity=float(request.form.get("quantity", 0)),
            unit=request.form.get("unit", "pcs"),
            unit_price=float(request.form.get("unit_price", 0)),
            reorder_level=float(request.form.get("reorder_level", 0)),
            hsn=request.form.get("hsn", ""),
            last_updated=date.today(),
        )
        cdb.add(item)
        cdb.commit()
        flash("Stock item added!")
        return redirect(url_for("inventory_list"))
    return render_template("inventory_form.html")


@app.route("/inventory/edit/<int:item_pk>", methods=["GET", "POST"])
@login_required
def inventory_edit(item_pk):
    cdb = get_cdb()
    company_id = get_current_company()
    item       = _first_or_404(cdb.query(StockItem).filter_by(id=item_pk, company_id=company_id).first())
    if request.method == "POST":
        item.name          = request.form.get("name", item.name)
        item.category      = request.form.get("category", item.category)
        item.quantity      = float(request.form.get("quantity", item.quantity))
        item.unit          = request.form.get("unit", item.unit)
        item.unit_price    = float(request.form.get("unit_price", item.unit_price))
        item.reorder_level = float(request.form.get("reorder_level", item.reorder_level))
        item.hsn           = request.form.get("hsn", item.hsn)
        item.last_updated  = date.today()
        cdb.commit()
        flash("Stock item updated!")
        return redirect(url_for("inventory_list"))
    return render_template("inventory_form.html", item=item)


@app.route("/inventory/delete/<int:item_pk>", methods=["POST"])
@login_required
def inventory_delete(item_pk):
    cdb = get_cdb()
    company_id = get_current_company()
    item       = _first_or_404(cdb.query(StockItem).filter_by(id=item_pk, company_id=company_id).first())
    cdb.delete(item)
    cdb.commit()
    flash("Stock item deleted.")
    return redirect(url_for("inventory_list"))

# ── Purchase Invoice Routes ─────────────────────────────────────────────────────────

@app.route("/purchase/list")
@login_required
def purchase_invoice_list():
    cdb = get_cdb()
    company_id = get_current_company()
    invoices = cdb.query(PurchaseInvoice).filter_by(company_id=company_id).order_by(PurchaseInvoice.date.desc()).all()

    print("=== Purchase Invoice Debug ===")
    for inv in invoices:
        print(f"ID: {inv.id}, invoice_id: {inv.invoice_id}, supplier: {inv.supplier.name if inv.supplier else 'None'}")
    
    total_amount = sum(p.grand_total for p in invoices)
    total_paid = sum(p.paid_amount for p in invoices)
    total_due = sum(p.balance for p in invoices)
    
    return render_template("purchases.html",
        purchases=invoices,
        total_amount=total_amount,
        total_paid=total_paid,
        total_due=total_due
    )

@app.route("/purchase/new", methods=["GET", "POST"])
@login_required
def purchase_invoice_new():
    cdb = get_cdb()
    company_id = get_current_company()
    suppliers = cdb.query(Client).filter(
        Client.company_id == company_id,
        db.or_(Client.client_type == "Supplier", Client.client_type == "Both")
    ).all()
    
    if request.method == "POST":
        supplier_id   = request.form.get("supplier_id")
        supplier_name = request.form.get("supplier_name", "").strip()

        # Auto-create supplier if typed manually and not in list
        if not supplier_id and supplier_name:
            existing = cdb.query(Client).filter_by(
                company_id=company_id, name=supplier_name
            ).first()
            if existing:
                supplier_id = existing.id
            else:
                new_supplier = Client(
                    company_id=company_id,
                    name=supplier_name,
                    client_type="Supplier",
                    status="Active",
                    created_at=date.today()
                )
                cdb.add(new_supplier)
                cdb.flush()
                supplier_id = new_supplier.id

        invoice_number = request.form.get("invoice_number", "").strip()
        invoice_date   = request.form.get("invoice_date") or str(date.today())
        notes          = request.form.get("notes", "").strip()

        subtotal    = float(request.form.get("amount_before_gst") or 0)
        grand_total = float(request.form.get("grand_total") or 0)
        tax_total   = round(grand_total - subtotal, 2)

        inv_count  = cdb.query(PurchaseInvoice).count()
        invoice_id = f"PURCHASE-INV-{datetime.now().strftime('%Y%m%d')}-{inv_count+1:03d}"

        purchase_inv = PurchaseInvoice(
            invoice_id=invoice_id,
            company_id=company_id,
            supplier_id=int(supplier_id) if supplier_id else None,
            supplier_name=supplier_name if not supplier_id else None,
            invoice_number=invoice_number,
            date=date.fromisoformat(invoice_date),
            subtotal=subtotal,
            tax_amount=tax_total,
            grand_total=grand_total,
            paid_amount=0,
            balance=grand_total,
            status="Pending",
            notes=notes,
            created_at=datetime.utcnow()
        )
        cdb.add(purchase_inv)
        cdb.flush()

        # Update supplier pending payable
        if supplier_id:
            supplier = cdb.get(Client, int(supplier_id))
            if supplier:
                supplier.pending = (supplier.pending or 0) + grand_total

        cdb.commit()

        # Handle file upload
        if "invoice_file" in request.files:
            file = request.files["invoice_file"]
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{invoice_id}_{file.filename}")
                filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(filepath)
                purchase_inv.file_path = filepath
                cdb.commit()

        flash(f"Purchase invoice {invoice_id} saved successfully!")
        return redirect(url_for("purchase_invoice_list"))

    return render_template("purchase_new.html",
                           suppliers=suppliers,
                           today=str(date.today()))

@app.route("/purchase/view/<invoice_id>")
@login_required
def purchase_invoice_view(invoice_id):
    cdb = get_cdb()
    company_id = get_current_company()
    invoice = cdb.query(PurchaseInvoice).filter_by(invoice_id=invoice_id, company_id=company_id).first()
    if not invoice:
        abort(404)
    
    return render_template("purchase_view.html", invoice=invoice)

"""@app.route("/purchase/pay/<int:pk>", methods=["POST"])
@login_required
def purchase_make_payment(pk):
    cdb = get_cdb()
    company_id = get_current_company()
    invoice = _first_or_404(cdb.query(PurchaseInvoice).filter_by(id=pk, company_id=company_id).first())
    
    amount = float(request.form.get("amount", 0))
    if amount > invoice.balance:
        flash("Payment amount exceeds pending balance!")
        return redirect(url_for("purchase_invoice_view", invoice_id=invoice.invoice_id))
    
    invoice.paid_amount += amount
    invoice.balance -= amount
    
    if invoice.balance == 0:
        invoice.status = "Paid"
    elif invoice.paid_amount > 0:
        invoice.status = "Partial"
    
    if invoice.supplier:
        invoice.supplier.pending -= amount
    
    cdb.commit()
    flash(f"Payment of ₹{amount:,.2f} recorded!")
    return redirect(url_for("purchase_invoice_view", invoice_id=invoice.invoice_id))"""
@app.route("/purchase/pay/<int:pk>", methods=["POST"])
@login_required
def purchase_make_payment(pk):
    cdb = get_cdb()
    company_id = get_current_company()
    invoice = _first_or_404(cdb.query(PurchaseInvoice).filter_by(id=pk, company_id=company_id).first())

    amount   = float(request.form.get("amount", 0))
    pay_mode = request.form.get("pay_mode", "Cash")
    narration= request.form.get("narration", "")

    if amount <= 0:
        flash("Invalid payment amount.")
        return redirect(url_for("purchase_invoice_view", invoice_id=invoice.invoice_id))

    if amount > (invoice.balance or 0):
        amount = invoice.balance or 0

    invoice.paid_amount = (invoice.paid_amount or 0) + amount
    invoice.balance     = max(0, (invoice.balance or 0) - amount)

    if invoice.balance <= 0:
        invoice.status = "Paid"
    elif invoice.paid_amount > 0:
        invoice.status = "Partial"

    if invoice.supplier:
        invoice.supplier.pending = max(0, (invoice.supplier.pending or 0) - amount)

    cdb.commit()
    flash(f"Payment of ₹{amount:,.2f} via {pay_mode} recorded. {narration}")
    return redirect(url_for("purchase_invoice_view", invoice_id=invoice.invoice_id))

# ─────────────────────────────────────────────────────────────────────────────
# ── Invoices ──────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
"""@app.route("/invoice/list")
@login_required
def invoice_list():
    cdb = get_cdb()
    company_id    = get_current_company()
    filter_status = request.args.get("status", "All")

    # Map template tab names -> DB status values
    status_map = {
        "paid":    "Paid",
        "partial": "Partial",
        "pending": "Draft",
    }

    query = cdb.query(Invoice).filter_by(company_id=company_id)
    if filter_status != "All":
        db_status = status_map.get(filter_status)
        if db_status:
            query = query.filter_by(status=db_status)

    raw_invoices = query.order_by(Invoice.date.desc()).all()

    invoices = []
    for inv in raw_invoices:
        if inv.client_obj:
            customer_name = inv.client_obj.name
        elif inv.contact_person:
            customer_name = inv.contact_person
        else:
            customer_name = "—"

        total = inv.grand_total or 0.0

        if inv.status == "Paid":
            paid       = total
            balance    = 0.0
            tab_status = "paid"
        elif inv.status == "Partial":
            paid       = inv.paid_amount if hasattr(inv, "paid_amount") and inv.paid_amount else (inv.subtotal or 0.0)
            balance    = inv.balance if hasattr(inv, "balance") and inv.balance is not None else total - paid
            tab_status = "partial"
        else:
            paid       = 0.0
            balance    = total
            tab_status = "pending"

        # Unpack shipment metadata stored as JSON in inv.terms
        meta = {}
        if inv.terms:
            try:
                meta = json.loads(inv.terms)
            except (ValueError, TypeError):
                meta = {}

        # Determine if this is a customer/shipment invoice (has AWB docket)
        docket_no = meta.get("docket_no", "")
        is_shipment = bool(docket_no) or inv.invoice_id.startswith("CUST-")

        invoices.append({
            "id":             inv.invoice_id,
            "customer_name":  customer_name,
            "date":           inv.date,
            "bill_type":      "credit",
            "total":          total,
            "paid":           paid,
            "balance":        balance,
            "status":         tab_status,
            # Shipment-specific fields unpacked from JSON terms
            "docket_no":      docket_no,
            "receiver_name":  meta.get("receiver_name", ""),
            "destination":    meta.get("destination", ""),
            "carrier":        meta.get("carrier", ""),
            "shipment_type":  meta.get("shipment_type", ""),
            "mode":           meta.get("mode", ""),
            "is_shipment":    is_shipment,
            "has_resale":     inv.has_resale if hasattr(inv, "has_resale") else False,
            "resale_charges": inv.resale_charges if hasattr(inv, "resale_charges") else 0,
            "resale_reason":  inv.resale_reason if hasattr(inv, "resale_reason") else "",
            "resale_date":    inv.resale_date if hasattr(inv, "resale_date") else None,
        })

    return render_template("invoice_list.html",
                           invoices=invoices,
                           current_status=filter_status)"""

@app.route("/invoice/list")
@login_required
def invoice_list():
    cdb = get_cdb()
    company_id    = get_current_company()
    filter_status = request.args.get("status", "All")

    # Map template tab names -> DB status values
    status_map = {
        "paid":    "Paid",
        "partial": "Partial",
        "pending": "Draft",
    }

    query = cdb.query(Invoice).filter_by(company_id=company_id)
    if filter_status != "All":
        db_status = status_map.get(filter_status)
        if db_status:
            query = query.filter_by(status=db_status)

    raw_invoices = query.order_by(Invoice.date.desc()).all()

    invoices = []
    for inv in raw_invoices:
        if inv.client_obj:
            customer_name = inv.client_obj.name
        elif inv.contact_person:
            customer_name = inv.contact_person
        else:
            customer_name = "—"

        # ── Get resale charges ──────────────────────────────────────────────
        resale_charges = getattr(inv, 'resale_charges', 0) or 0
        resale_gst = resale_charges * 0.18  # 18% GST
        resale_total = resale_charges + resale_gst
        
        # ── Total includes resale ────────────────────────────────────────────
        total = inv.grand_total or 0.0

        if inv.status == "Paid":
            paid       = total
            balance    = 0.0
            tab_status = "paid"
        elif inv.status == "Partial":
            paid       = inv.paid_amount if hasattr(inv, "paid_amount") and inv.paid_amount else (inv.subtotal or 0.0)
            balance    = inv.balance if hasattr(inv, "balance") and inv.balance is not None else total - paid
            tab_status = "partial"
        else:
            paid       = 0.0
            balance    = total
            tab_status = "pending"

        # Unpack shipment metadata stored as JSON in inv.terms
        meta = {}
        if inv.terms:
            try:
                meta = json.loads(inv.terms)
            except (ValueError, TypeError):
                meta = {}

        # Determine if this is a customer/shipment invoice (has AWB docket)
        docket_no = meta.get("docket_no", "")
        is_shipment = bool(docket_no) or inv.invoice_id.startswith("CUST-")

        invoices.append({
            "id":             inv.invoice_id,
            "customer_name":  customer_name,
            "date":           inv.date,
            "bill_type":      "credit",
            "total":          total,  # ← Now includes resale
            "paid":           paid,
            "balance":        balance,
            "status":         tab_status,
            # Shipment-specific fields unpacked from JSON terms
            "docket_no":      docket_no,
            "receiver_name":  meta.get("receiver_name", ""),
            "destination":    meta.get("destination", ""),
            "carrier":        meta.get("carrier", ""),
            "shipment_type":  meta.get("shipment_type", ""),
            "mode":           meta.get("mode", ""),
            "is_shipment":    is_shipment,
            # Resale fields
            "has_resale":     getattr(inv, 'has_resale', False),
            "resale_charges": resale_charges,
            "resale_reason":  getattr(inv, 'resale_reason', ''),
            "resale_date":    getattr(inv, 'resale_date', None),
            "resale_total":   resale_total,  # ← NEW: total including GST
        })

    return render_template("invoice_list.html",
                           invoices=invoices,
                           current_status=filter_status)


@app.route("/invoice/new", methods=["GET", "POST"])
@login_required
def invoice_new():
    cdb = get_cdb()
    company_id = get_current_company()
    clients = cdb.query(Client).filter(
        Client.company_id == company_id,
        ~Client.client_type.in_(["Supplier", "Both"])  
    ).all()

    price_lists = cdb.query(PriceList).filter_by(
        company_id=company_id, 
        is_active=True
    ).all()

    # Check if we're editing an existing invoice
    edit_id = request.args.get("edit")
    existing_invoice = None
    if edit_id:
        existing_invoice = cdb.query(Invoice).filter_by(invoice_id=edit_id, company_id=company_id).first()
        if not existing_invoice:
            flash("Invoice not found")
            return redirect(url_for("invoice_list"))

    if request.method == "POST":
        # Handle customer invoice POST (save/update)
        # This is for the customer invoice form
        client_id_raw = request.form.get("customer_id")
        client_id = int(client_id_raw) if client_id_raw else None
        invoice_date = request.form.get("invoice_date") or str(date.today())
        docket_no = request.form.get("docket_no", "")
        action = request.form.get("action", "final")

        # Charges & totals
        freight = float(request.form.get("freight_amount", 0) or 0)
        fuel = float(request.form.get("fuel_surcharge", 0) or 0)
        other = float(request.form.get("other_charges", 0) or 0)
        base = freight + fuel + other
        gst = round(base * 0.18, 2)
        grand_total = round(base + gst, 2)
        amount_paid = float(request.form.get("amount_paid", 0) or 0)
        balance = round(grand_total - amount_paid, 2)

        # Payment info
        payment_mode = request.form.get("payment_mode", "cash")
        upi_app = request.form.get("upi_app", "")
        upi_ref = request.form.get("upi_ref", "")
        cheque_no = request.form.get("cheque_no", "")
        cheque_date = request.form.get("cheque_date", "")
        cheque_bank = request.form.get("cheque_bank", "")

        # Status
        if action == "draft":
            status = "Draft"
        elif balance <= 0:
            status = "Paid"
        elif amount_paid > 0:
            status = "Partial"
        else:
            status = "Draft"

        notes = request.form.get("notes", "")
        
        # Process Packages
        pkg_names = request.form.getlist("pkg_name[]")
        pkg_types = request.form.getlist("pkg_type[]")
        pkg_qtys = request.form.getlist("pkg_qty[]")
        pkg_l = request.form.getlist("pkg_l[]")
        pkg_w = request.form.getlist("pkg_w[]")
        pkg_h = request.form.getlist("pkg_h[]")
        pkg_wt = request.form.getlist("pkg_wt[]")
        pkg_rates = request.form.getlist("pkg_rate[]")
        
        packages_data = []
        for i in range(len(pkg_names)):
            if pkg_names[i] and pkg_names[i].strip():
                packages_data.append({
                    "name": pkg_names[i],
                    "type": pkg_types[i] if i < len(pkg_types) else "",
                    "qty": float(pkg_qtys[i] or 1) if pkg_qtys[i] else 1,
                    "length": float(pkg_l[i] or 0) if i < len(pkg_l) else 0,
                    "width": float(pkg_w[i] or 0) if i < len(pkg_w) else 0,
                    "height": float(pkg_h[i] or 0) if i < len(pkg_h) else 0,
                    "weight": float(pkg_wt[i] or 0) if i < len(pkg_wt) else 0,
                    "rate": float(pkg_rates[i] or 0) if i < len(pkg_rates) else 0,
                })
        
        # Shipment metadata
        shipment_meta = json.dumps({
            "docket_no": docket_no,
            "shipper_name": request.form.get("shipper_name", ""),
            "shipper_address": request.form.get("shipper_address", ""),
            "receiver_name": request.form.get("receiver_name", ""),
            "receiver_phone": request.form.get("receiver_phone", ""),
            "receiver_address": request.form.get("receiver_address", ""),
            "destination": request.form.get("destination", ""),
            "shipment_type": request.form.get("shipment_type", ""),
            "mode": request.form.get("mode", ""),
            "carrier": request.form.get("carrier", ""),
            "carrier_ref": request.form.get("carrier_ref", ""),
            "origin": request.form.get("origin", "India"),
            "pickup_date": request.form.get("pickup_date", ""),
            "departure_time": request.form.get("departure_time", ""),
            "expected_delivery": request.form.get("expected_delivery", ""),
            "comments": request.form.get("comments", ""),
            "payment_mode": payment_mode,
            "upi_app": upi_app,
            "upi_ref": upi_ref,
            "cheque_no": cheque_no,
            "cheque_date": cheque_date,
            "cheque_bank": cheque_bank,
            "freight": freight,
            "fuel": fuel,
            "other": other,
            "freight_weight": freight_weight,
            "freight_rate_per_kg": freight_rate,
            "other_charges_reason": request.form.get("other_charges_reason", ""),
            "gst": gst,
            "amount_paid": amount_paid,
            "packages": packages_data,
        })

        # Check if we're updating an existing invoice
        edit_invoice_id = request.form.get("edit_invoice_id")
        if edit_invoice_id:
            # Update existing invoice
            invoice = cdb.query(Invoice).filter_by(invoice_id=edit_invoice_id, company_id=company_id).first()
            if invoice:
                invoice.client_id = client_id
                invoice.date = date.fromisoformat(invoice_date)
                invoice.status = status
                invoice.contact_person = request.form.get("shipper_name", "")
                invoice.phone = request.form.get("customer_phone", "")
                invoice.subtotal = base
                invoice.tax_amount = gst
                invoice.grand_total = grand_total
                invoice.terms = shipment_meta
                invoice.email = notes
                invoice.paid_amount = amount_paid
                invoice.balance = balance
                
                cdb.commit()
                flash(f"Customer invoice {invoice.invoice_id} updated successfully!")
                return redirect(url_for("invoice_list"))
        else:
            # Create new invoice
            cust_count = cdb.query(Invoice).filter_by(company_id=company_id).filter(Invoice.invoice_id.like("CUST-%")).count()
            invoice_id = f"CUST-{datetime.now().strftime('%Y%m%d')}-{cust_count + 1:03d}"
            
            inv = Invoice(
                invoice_id=invoice_id,
                company_id=company_id,
                client_id=client_id,
                date=date.fromisoformat(invoice_date),
                status=status,
                contact_person=request.form.get("shipper_name", ""),
                phone=request.form.get("customer_phone", ""),
                subtotal=base,
                tax_amount=gst,
                grand_total=grand_total,
                terms=shipment_meta,
                email=notes,
                paid_amount=amount_paid,
                balance=balance,
            )
            cdb.add(inv)
            cdb.commit()
            
            flash(f"Customer invoice {invoice_id} created successfully!")
            return redirect(url_for("invoice_list"))

    # GET request - prepare form data
    form_data = {}
    packages = []
    invoice_id = None
    invoice_date = str(date.today())
    docket_no = ""
    is_edit = False
    
    if existing_invoice:
        is_edit = True
        invoice_id = existing_invoice.invoice_id
        invoice_date = existing_invoice.date.strftime('%Y-%m-%d')
        
        # Parse the terms JSON to get all the stored data
        try:
            meta = json.loads(existing_invoice.terms) if existing_invoice.terms else {}
        except:
            meta = {}
        
        # Build form_data with all existing values
        form_data = {
            "customer_id": existing_invoice.client_id,
            "customer_phone": existing_invoice.phone or "",
            "shipper_name": meta.get("shipper_name", existing_invoice.contact_person or ""),
             "shipper_address1": meta.get("shipper_address1", meta.get("shipper_address", "")),  
            "shipper_address2": meta.get("shipper_address2", ""),  
            "shipper_city": meta.get("shipper_city", ""),  
            "shipper_state": meta.get("shipper_state", ""),  
            "shipper_pincode": meta.get("shipper_pincode", ""),  
            "shipper_country": meta.get("shipper_country", "India"), 
            "receiver_name": meta.get("receiver_name", ""),
            "receiver_phone": meta.get("receiver_phone", ""),
            "receiver_address1": meta.get("receiver_address1", meta.get("receiver_address", "")),  
            "receiver_address2": meta.get("receiver_address2", ""),  
            "receiver_city": meta.get("receiver_city", ""),  
            "receiver_state": meta.get("receiver_state", ""),  
            "receiver_pincode": meta.get("receiver_pincode", ""),  
            "receiver_country": meta.get("receiver_country", "India"),
            "destination": meta.get("destination", ""),
            "shipment_type": meta.get("shipment_type", ""),
            "mode": meta.get("mode", ""),
            "carrier": meta.get("carrier", ""),
            "carrier_ref": meta.get("carrier_ref", ""),
            "origin": meta.get("origin", "India"),
            "pickup_date": meta.get("pickup_date", ""),
            "departure_time": meta.get("departure_time", ""),
            "expected_delivery": meta.get("expected_delivery", ""),
            "comments": meta.get("comments", ""),
            "freight": meta.get("freight", existing_invoice.subtotal or 0),
            "fuel": meta.get("fuel", 0),
            "other": meta.get("other", 0),
            "freight_weight": meta.get("freight_weight", 0),
            "freight_rate_per_kg": meta.get("freight_rate_per_kg", 0),
            "other_charges_reason": meta.get("other_charges_reason", ""),
            "amount_paid": meta.get("amount_paid", existing_invoice.paid_amount or 0),
            "payment_mode": meta.get("payment_mode", "cash"),
            "upi_app": meta.get("upi_app", ""),
            "upi_ref": meta.get("upi_ref", ""),
            "cheque_no": meta.get("cheque_no", ""),
            "cheque_date": meta.get("cheque_date", ""),
            "cheque_bank": meta.get("cheque_bank", ""),
            "notes": existing_invoice.email or "",
            "docket_no": meta.get("docket_no", ""),
            "has_resale": getattr(existing_invoice, 'has_resale', False),
            "resale_charges": getattr(existing_invoice, 'resale_charges', 0),
            "resale_reason": getattr(existing_invoice, 'resale_reason', ''),
            "resale_date": getattr(existing_invoice, 'resale_date', ''),
            "resale_notes": getattr(existing_invoice, 'resale_notes', ''),
        }
        
        docket_no = meta.get("docket_no", "")
        
        # Get packages from meta
        packages = meta.get("packages", [])
        
        # If no packages in meta, create default empty package
        if not packages:
            packages = [{"name": "", "type": "", "qty": 1, "length": "", "width": "", "height": "", "weight": "", "rate": 0}]
    else:
        # New invoice - default values
        cust_count = cdb.query(Invoice).filter_by(company_id=company_id).filter(Invoice.invoice_id.like("CUST-%")).count()
        invoice_id = f"CUST-{datetime.now().strftime('%Y%m%d')}-{cust_count + 1:03d}"
        docket_no = _next_awb_number(company_id)
        form_data = {
            "payment_mode": "cash"
        }
        packages = [{"name": "Box", "type": "Box", "qty": 1, "length": "", "width": "", "height": "", "weight": "", "rate": 0}]

    return render_template("invoice.html",
                           clients=clients,
                           form_data=form_data,
                           packages=packages,
                           invoice_id=invoice_id,
                           invoice_date=invoice_date,
                           docket_no=docket_no,
                           is_edit=is_edit,
                           today=str(date.today()),
                           price_lists=price_lists,
                           invoice=existing_invoice)


@app.route("/invoice/edit/<invoice_id>", methods=["GET", "POST"])
@login_required
def invoice_edit(invoice_id):
    """GET: render the edit form. POST: save updated line-item invoice."""
    cdb = get_cdb()
    company_id = get_current_company()

    invoice = _first_or_404(cdb.query(Invoice).filter_by(
        invoice_id=invoice_id, company_id=company_id).first())

    clients = cdb.query(Client).filter(
        Client.company_id == company_id,
        ~Client.client_type.in_(["Supplier", "Both"])  
    ).all()

    price_lists = cdb.query(PriceList).filter_by(
        company_id=company_id, 
        is_active=True
    ).all()

    if request.method == "POST":
        # ── Basic fields ────────────────────────────────────────────────────
        client_id_raw = request.form.get("client_id")
        invoice.client_id    = int(client_id_raw) if client_id_raw else None
        invoice.contact_person = request.form.get("contact_person", "")
        invoice.email        = request.form.get("email", "")
        invoice.phone        = request.form.get("phone", "")
        invoice.status       = request.form.get("status", "Draft")
        invoice.terms        = request.form.get("terms", "")

        invoice_date_str = request.form.get("invoice_date")
        if invoice_date_str:
            invoice.date = date.fromisoformat(invoice_date_str)

        due_date_str = request.form.get("due_date")
        invoice.due_date = date.fromisoformat(due_date_str) if due_date_str else None

        # ── Line items: delete old, insert new ──────────────────────────────
        cdb.query(InvoiceItem).filter_by(invoice_id=invoice.id).delete()

        item_codes   = request.form.getlist("item_code[]")
        descriptions = request.form.getlist("description[]")
        qtys         = request.form.getlist("qty[]")
        rates        = request.form.getlist("rate[]")
        discounts    = request.form.getlist("discount[]")

        subtotal = 0.0
        for i, desc in enumerate(descriptions):
            if not desc or not desc.strip():
                continue
            qty      = float(qtys[i])      if i < len(qtys)      and qtys[i]      else 0.0
            rate     = float(rates[i])     if i < len(rates)     and rates[i]     else 0.0
            discount = float(discounts[i]) if i < len(discounts) and discounts[i] else 0.0
            line_amt = qty * rate * (1 - discount / 100)
            subtotal += line_amt

            cdb.add(InvoiceItem(
                invoice_id    = invoice.id,
                code          = item_codes[i] if i < len(item_codes) else "",
                description   = desc.strip(),
                qty           = qty,
                rate          = rate,
                discount      = discount,
            ))

        tax_amount  = round(subtotal * 0.18, 2)
        grand_total = round(subtotal + tax_amount, 2)

        invoice.subtotal    = round(subtotal, 2)
        invoice.tax_amount  = tax_amount
        invoice.grand_total = grand_total
        invoice.balance     = round(grand_total - (invoice.paid_amount or 0), 2)

        cdb.commit()
        flash(f"Invoice {invoice_id} updated successfully!", "success")
        return redirect(url_for("invoice_list"))

    # ── GET: build items list for the template ───────────────────────────────
    items = cdb.query(InvoiceItem).filter_by(invoice_id=invoice.id).all()
    today    = str(date.today())
    due_date = str((date.today() + timedelta(days=30)))

    return render_template("invoice_edit.html",
                           invoice=invoice,
                           clients=clients,
                           items=items,
                           today=today,
                           due_date=due_date,
                           price_lists=price_lists)

@app.route("/invoice/customer/update", methods=["POST"])
@login_required
def invoice_customer_update():
    """Update an existing customer invoice"""
    cdb = get_cdb()
    company_id = get_current_company()
    edit_invoice_id = request.form.get("edit_invoice_id")
    
    # Find the existing invoice
    invoice = cdb.query(Invoice).filter_by(invoice_id=edit_invoice_id, company_id=company_id).first()
    if not invoice:
        flash("Invoice not found")
        return redirect(url_for("invoice_list"))
    
    price_lists = cdb.query(PriceList).filter_by(
        company_id=company_id, 
        is_active=True
    ).all()

    # Parse the existing terms JSON
    try:
        old_meta = json.loads(invoice.terms) if invoice.terms else {}
    except:
        old_meta = {}
    
    # ── Basic fields ──────────────────────────────────────────────────────────
    client_id_raw = request.form.get("customer_id")
    client_id = int(client_id_raw) if client_id_raw else None
    invoice_date = request.form.get("invoice_date") or str(date.today())
    docket_no = request.form.get("docket_no", "")
    action = request.form.get("action", "final")

    # ── Charges & totals ──────────────────────────────────────────────────────
    freight_weight = float(request.form.get("freight_weight", 0) or 0)
    freight_rate   = float(request.form.get("freight_rate_per_kg", 0) or 0)
    freight        = round(freight_weight * freight_rate, 2)
    fuel = float(request.form.get("fuel_surcharge", 0) or 0)
    other = float(request.form.get("other_charges", 0) or 0)
    base = freight + fuel + other
    co = Company.query.filter_by(company_id=company_id).first()
    apply_gst = co.is_gst_registered if (co and hasattr(co, 'is_gst_registered')) else True
    gst = round(base * 0.18, 2) if apply_gst else 0.0
    grand_total = round(base + gst, 2)
    amount_paid = float(request.form.get("amount_paid", 0) or 0)
    balance = round(grand_total - amount_paid, 2)

     # ── Resale Charges ──────────────────────────────────────────────────────────
     # ── Resale Charges ──────────────────────────────────────────────────────────
    has_resale = request.form.get("resale_active") == "true"
    resale_amount = float(request.form.get("resale_amount", 0) or 0)
    resale_reason = request.form.get("resale_reason", "").strip()
    resale_date_str = request.form.get("resale_date")
    resale_notes = request.form.get("resale_notes", "").strip()
    
    # Apply GST to resale charges
    if has_resale and resale_amount > 0:
        co = Company.query.filter_by(company_id=company_id).first()
        apply_gst = co.is_gst_registered if (co and hasattr(co, 'is_gst_registered')) else True
        resale_gst = round(resale_amount * 0.18, 2) if apply_gst else 0.0
        
        # Add resale to totals
        base_with_resale = base + resale_amount
        gst_total = round(base_with_resale * 0.18, 2) if apply_gst else 0.0
        grand_total = round(base_with_resale + gst_total, 2)
        
        resale_date = date.fromisoformat(resale_date_str) if resale_date_str else date.today()
    else:
        resale_amount = 0
        resale_gst = 0
        resale_date = None
        resale_reason = None
        resale_notes = None
        base_with_resale = base
        gst_total = gst
        grand_total = round(base + gst, 2)

    balance = round(grand_total - amount_paid, 2)

    # ── Payment info ─────────────────────────────────────────────────────────
    payment_mode = request.form.get("payment_mode", "cash")
    upi_app = request.form.get("upi_app", "")
    upi_ref = request.form.get("upi_ref", "")
    cheque_no = request.form.get("cheque_no", "")
    cheque_date = request.form.get("cheque_date", "")
    cheque_bank = request.form.get("cheque_bank", "")

    # ── Status ────────────────────────────────────────────────────────────────
    if action == "draft":
        status = "Draft"
    elif balance <= 0:
        status = "Paid"
    elif amount_paid > 0:
        status = "Partial"
    else:
        status = "Draft"

    notes = request.form.get("notes", "")
    
    # ── Process Packages ─────────────────────────────────────────────────────
    pkg_names = request.form.getlist("pkg_name[]")
    pkg_types = request.form.getlist("pkg_type[]")
    pkg_qtys = request.form.getlist("pkg_qty[]")
    pkg_l = request.form.getlist("pkg_l[]")
    pkg_w = request.form.getlist("pkg_w[]")
    pkg_h = request.form.getlist("pkg_h[]")
    pkg_wt = request.form.getlist("pkg_wt[]")
    pkg_rates = request.form.getlist("pkg_rate[]")
    
    packages_data = []
    for i in range(len(pkg_names)):
        if pkg_names[i] and pkg_names[i].strip():
            packages_data.append({
                "name": pkg_names[i],
                "type": pkg_types[i] if i < len(pkg_types) else "",
                "qty": float(pkg_qtys[i] or 1) if pkg_qtys[i] else 1,
                "length": float(pkg_l[i] or 0) if i < len(pkg_l) else 0,
                "width": float(pkg_w[i] or 0) if i < len(pkg_w) else 0,
                "height": float(pkg_h[i] or 0) if i < len(pkg_h) else 0,
                "weight": float(pkg_wt[i] or 0) if i < len(pkg_wt) else 0,
                "rate": float(pkg_rates[i] or 0) if i < len(pkg_rates) else 0,
            })
    
    # Update shipment metadata
    shipment_meta = json.dumps({
        "docket_no": docket_no,
        "shipper_name": request.form.get("shipper_name", ""),
        "shipper_address1": request.form.get("shipper_address1", ""),  
        "shipper_address2": request.form.get("shipper_address2", ""),  
        "shipper_city": request.form.get("shipper_city", ""),  
        "shipper_state": request.form.get("shipper_state", ""),  
        "shipper_pincode": request.form.get("shipper_pincode", ""),  
        "shipper_country": request.form.get("shipper_country", "India"),
        "receiver_name": request.form.get("receiver_name", ""),
        "receiver_phone": request.form.get("receiver_phone", ""),
        "receiver_address1": request.form.get("receiver_address1", ""),  
        "receiver_address2": request.form.get("receiver_address2", ""),  
        "receiver_city": request.form.get("receiver_city", ""),  
        "receiver_state": request.form.get("receiver_state", ""),  
        "receiver_pincode": request.form.get("receiver_pincode", ""),  
        "receiver_country": request.form.get("receiver_country", "India"),
        "destination": request.form.get("destination", ""),
        "shipment_type": request.form.get("shipment_type", ""),
        "mode": request.form.get("mode", ""),
        "carrier": request.form.get("carrier", ""),
        "carrier_ref": request.form.get("carrier_ref", ""),
        "origin": request.form.get("origin", "India"),
        "pickup_date": request.form.get("pickup_date", ""),
        "departure_time": request.form.get("departure_time", ""),
        "expected_delivery": request.form.get("expected_delivery", ""),
        "comments": request.form.get("comments", ""),
        "payment_mode": payment_mode,
        "upi_app": upi_app,
        "upi_ref": upi_ref,
        "cheque_no": cheque_no,
        "cheque_date": cheque_date,
        "cheque_bank": cheque_bank,
        "freight": freight,
        "freight_weight": freight_weight,
        "freight_rate_per_kg": freight_rate,
        "fuel": fuel,
        "other": other,
        "other_charges_reason": request.form.get("other_charges_reason", ""),
        "gst": gst,
        "amount_paid": amount_paid,
        "packages": packages_data,
        "resale": {
            "amount": resale_amount,
            "gst": resale_gst if has_resale else 0,
            "reason": resale_reason,
            "date": resale_date.strftime("%Y-%m-%d") if resale_date else "",
            "notes": resale_notes,
            "added_by": get_current_user().get("email")
        } if has_resale and resale_amount > 0 else None
    })
    

    # Update invoice fields
    invoice.client_id = client_id
    invoice.date = date.fromisoformat(invoice_date)
    invoice.status = status
    invoice.contact_person = request.form.get("shipper_name", "")
    invoice.phone = request.form.get("customer_phone", "")
    invoice.subtotal = base
    invoice.tax_amount = gst
    invoice.grand_total = grand_total
    invoice.terms = shipment_meta
    invoice.email = notes
    invoice.paid_amount = amount_paid
    invoice.balance = balance
    invoice.has_resale = has_resale and resale_amount > 0
    invoice.resale_charges = resale_amount
    invoice.resale_reason = resale_reason
    invoice.resale_date = resale_date
    invoice.resale_notes = resale_notes

    cdb.commit()

    flash(f"Customer invoice {invoice.invoice_id} updated successfully!")
    return redirect(url_for("invoice_list"))

@app.route("/invoice/view/<invoice_id>")
@login_required
def invoice_view(invoice_id):
    cdb = get_cdb()
    company_id = get_current_company()
    inv        = _first_or_404(cdb.query(Invoice).filter_by(invoice_id=invoice_id, company_id=company_id).first())

    # Resolve customer name & phone
    if inv.client_obj:
        customer_name  = inv.client_obj.name
        customer_phone = inv.client_obj.phone or inv.phone or ""
    else:
        customer_name  = inv.contact_person or "—"
        customer_phone = inv.phone or ""

    total    = inv.grand_total or 0.0
    subtotal = inv.subtotal    or 0.0
    tax      = inv.tax_amount  or 0.0

    # Derive paid / balance / tab-status from DB status
    db_status = (inv.status or "").lower()
    if db_status == "paid":
        paid       = total
        balance    = 0.0
        tab_status = "paid"
    elif db_status == "partial":
        paid       = subtotal
        balance    = total - paid
        tab_status = "partial"
    else:
        paid       = 0.0
        balance    = total
        tab_status = "pending"

    # Normalize line items — template uses item.desc, item.code, item.qty,
    # item.rate, item.discount
    items = []
    for li in inv.items:
        qty      = li.qty      or 0.0
        rate     = li.rate     or 0.0
        discount = li.discount or 0.0
        items.append({
            "code":     li.code        or "",
            "desc":     li.description or "",
            "qty":      qty,
            "rate":     rate,
            "discount": discount,
            "amount":   qty * rate * (1 - discount / 100),
        })

    # Unpack shipment metadata stored as JSON in inv.terms
    meta = {}
    if inv.terms:
        try:
            meta = json.loads(inv.terms)
        except (ValueError, TypeError):
            meta = {}

    invoice = {
        "id":               inv.invoice_id,
        "date":             inv.date,
        "due_date":         inv.due_date,
        "status":           tab_status,
        "customer_name":    customer_name,
        "customer_phone":   customer_phone,
        "subtotal":         subtotal,
        "tax":              tax,
        "total":            total,
        "paid":             paid,
        "balance":          balance,
        "bill_type":        "credit",
        "items":            items,
        "related_orders":   [],
        "docket_no":        meta.get("docket_no", inv.invoice_id),
        "shipper_name":     meta.get("shipper_name", inv.contact_person or ""),
        "shipper_address1": meta.get("shipper_address1", ""),
        "shipper_address2": meta.get("shipper_address2", ""),
        "shipper_city": meta.get("shipper_city", ""),
        "shipper_state": meta.get("shipper_state", ""),
        "shipper_pincode": meta.get("shipper_pincode", ""),
        "shipper_country": meta.get("shipper_country", ""),
        "receiver_name": meta.get("receiver_name", ""),
        "receiver_phone": meta.get("receiver_phone", ""),
        "receiver_address1": meta.get("receiver_address1", ""),
        "receiver_address2": meta.get("receiver_address2", ""),
        "receiver_city": meta.get("receiver_city", ""),
        "receiver_state": meta.get("receiver_state", ""),
        "receiver_pincode": meta.get("receiver_pincode", ""),
        "receiver_country": meta.get("receiver_country", ""),
        "destination":      meta.get("destination", ""),
        "shipment_type":    meta.get("shipment_type", ""),
        "mode":             meta.get("mode", ""),
        "carrier":          meta.get("carrier", ""),
        "carrier_ref":      meta.get("carrier_ref", ""),
        "payment_mode":     meta.get("payment_mode", "credit"),
        "upi_app":          meta.get("upi_app", ""),
        "transaction_id":   meta.get("upi_ref", ""),
        "cheque_no":        meta.get("cheque_no", ""),
        "cheque_bank":      meta.get("cheque_bank", ""),
        "freight":          meta.get("freight", subtotal),
        "freight_weight":        meta.get("freight_weight", 0),
        "freight_rate_per_kg":   meta.get("freight_rate_per_kg", 0),
        "fuel_charge":      meta.get("fuel", 0),
        "other_charges":    meta.get("other", 0),
        "other_charges_reason": meta.get("other_charges_reason", ""),
        "notes":            inv.email or "",
        "packages":         [],
    }

    return render_template("invoice_view.html", invoice=invoice)

# ─────────────────────────────────────────────────────────────────────────────
# ── Resale / Return Charges Routes ──────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/invoice/<invoice_id>/resale-charges", methods=["GET", "POST"])
@login_required
def invoice_resale_charges(invoice_id):
    """Add return/resale charges to an existing invoice"""
    cdb = get_cdb()
    company_id = get_current_company()
    
    invoice = cdb.query(Invoice).filter_by(invoice_id=invoice_id, company_id=company_id).first()
    if not invoice:
        flash("Invoice not found")
        return redirect(url_for("invoice_list"))
    
    if request.method == "POST":
        action = request.form.get("action", "add")
        
        if action == "add":
            resale_amount = float(request.form.get("resale_amount", 0) or 0)
            resale_reason = request.form.get("resale_reason", "").strip()
            resale_date_str = request.form.get("resale_date")
            resale_notes = request.form.get("resale_notes", "").strip()
            
            if resale_amount <= 0:
                flash("Please enter a valid resale charge amount")
                return redirect(url_for("invoice_resale_charges", invoice_id=invoice_id))
            
            if not resale_reason:
                flash("Please select or enter a reason for the resale charge")
                return redirect(url_for("invoice_resale_charges", invoice_id=invoice_id))
            
            # Calculate GST on resale charges (if company is GST registered)
            co = Company.query.filter_by(company_id=company_id).first()
            apply_gst = co.is_gst_registered if (co and hasattr(co, 'is_gst_registered')) else True
            gst_on_resale = round(resale_amount * 0.18, 2) if apply_gst else 0.0
            
            # Update invoice with resale charges
            invoice.has_resale = True
            invoice.resale_charges = resale_amount
            invoice.resale_reason = resale_reason
            invoice.resale_date = date.fromisoformat(resale_date_str) if resale_date_str else date.today()
            invoice.resale_notes = resale_notes
            
            # Update totals - add resale amount to existing totals
            old_grand_total = invoice.grand_total or 0
            old_tax_amount = invoice.tax_amount or 0
            
            # Add resale amount to subtotal (or you can add separately)
            invoice.subtotal = (invoice.subtotal or 0) + resale_amount
            invoice.tax_amount = (invoice.tax_amount or 0) + gst_on_resale
            invoice.grand_total = (invoice.grand_total or 0) + resale_amount + gst_on_resale
            
            # Update balance
            invoice.balance = (invoice.balance or 0) + resale_amount + gst_on_resale
            
            # Update status if balance > 0
            if invoice.balance > 0:
                invoice.status = "Partial" if invoice.status == "Paid" else invoice.status
            
            # Store resale details in terms JSON for easy retrieval
            try:
                meta = json.loads(invoice.terms) if invoice.terms else {}
            except:
                meta = {}
            
            meta["resale"] = {
                "amount": resale_amount,
                "gst": gst_on_resale,
                "reason": resale_reason,
                "date": (date.fromisoformat(resale_date_str) if resale_date_str else date.today()).strftime("%Y-%m-%d"),
                "notes": resale_notes,
                "added_by": get_current_user().get("email")
            }
            invoice.terms = json.dumps(meta)
            
            # Create a cash transaction for the resale charge
            # (this is a NEW charge, so it's income)
            cash_txn = CashTransaction(
                company_id=company_id,
                type="income",
                date=date.fromisoformat(resale_date_str) if resale_date_str else date.today(),
                category="Resale Charges",
                description=f"Resale charge for invoice {invoice_id}: {resale_reason}",
                amount=resale_amount + gst_on_resale,
                reference=invoice_id,
                notes=f"Resale charge - {resale_reason}\n{resale_notes}",
                created_by=get_current_user().get("email")
            )
            cdb.add(cash_txn)
            
            # Update client pending balance
            client = cdb.query(Client).filter_by(id=invoice.client_id, company_id=company_id).first()
            if client and hasattr(client, "pending"):
                client.pending = (client.pending or 0) + resale_amount + gst_on_resale
            
            cdb.commit()
            flash(f"✅ Resale charge of ₹{resale_amount:,.2f} (+ GST ₹{gst_on_resale:,.2f}) added to invoice {invoice_id}")
            
        elif action == "remove":
            # Remove resale charges from invoice
            if invoice.has_resale:
                # Restore original totals (subtract resale charges)
                try:
                    meta = json.loads(invoice.terms) if invoice.terms else {}
                    resale_data = meta.get("resale", {})
                    resale_amount = resale_data.get("amount", 0)
                    resale_gst = resale_data.get("gst", 0)
                    
                    # Subtract from totals
                    invoice.subtotal = max(0, (invoice.subtotal or 0) - resale_amount)
                    invoice.tax_amount = max(0, (invoice.tax_amount or 0) - resale_gst)
                    invoice.grand_total = max(0, (invoice.grand_total or 0) - resale_amount - resale_gst)
                    invoice.balance = max(0, (invoice.balance or 0) - resale_amount - resale_gst)
                    
                    # Update client pending balance
                    client = cdb.query(Client).filter_by(id=invoice.client_id, company_id=company_id).first()
                    if client and hasattr(client, "pending"):
                        client.pending = max(0, (client.pending or 0) - resale_amount - resale_gst)
                    
                    # Remove resale data from terms
                    meta.pop("resale", None)
                    invoice.terms = json.dumps(meta) if meta else None
                    
                    invoice.has_resale = False
                    invoice.resale_charges = 0
                    invoice.resale_reason = None
                    invoice.resale_date = None
                    invoice.resale_notes = None
                    
                    # Recalculate status
                    if invoice.balance <= 0:
                        invoice.status = "Paid"
                    elif invoice.paid_amount > 0:
                        invoice.status = "Partial"
                    
                    cdb.commit()
                    flash(f"✅ Resale charges removed from invoice {invoice_id}")
                except Exception as e:
                    flash(f"Error removing resale charges: {str(e)}", "error")
            else:
                flash("No resale charges found on this invoice", "warning")
        
        return redirect(url_for("invoice_view", invoice_id=invoice_id))
    
    # GET - show the form
    # Parse existing terms to see if there's already resale data
    resale_data = None
    try:
        meta = json.loads(invoice.terms) if invoice.terms else {}
        resale_data = meta.get("resale")
    except:
        pass
    
    return render_template("invoice_resale.html", 
                         invoice=invoice, 
                         resale_data=resale_data,
                         today=str(date.today()))

# ─────────────────────────────────────────────────────────────────────────────
# ── Customer Invoice (Shipment) ───────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

AWB_PREFIX   = "AHL"
AWB_START    = 81000          # first number: AHL81000
AWB_COUNTER_KEY = "awb_last" # we store the last-used counter in a tiny helper


"""def _next_awb_number(company_id: int) -> str:
    
    # Count how many customer invoices already have an AHL docket number
    existing_count = (
        cdb.query(Invoice)
        .filter(
            Invoice.company_id == company_id,
            Invoice.terms.like("AWB:AHL%"),   # we embed the AWB in terms for storage
        )
        .count()
    )
    # Alternatively, just count all customer-type invoices for this company
    # (simpler and still gapless)
    cust_count = (
        cdb.query(Invoice)
        .filter(
            Invoice.company_id == company_id,
            Invoice.invoice_id.like("CUST-%"),
        )
        .count()
    )
    seq = AWB_START + cust_count
    return f"{AWB_PREFIX}{seq}"""
def _next_awb_number(company_id):
    """Generate the next sequential AWB/docket number for this company."""
    cdb = get_cdb()
    cust_count = cdb.query(Invoice).filter_by(company_id=company_id).filter(Invoice.invoice_id.like("CUST-%")).count()
    AWB_PREFIX = "AHL"
    AWB_START = 81000
    seq = AWB_START + cust_count
    return f"{AWB_PREFIX}{seq}"

@app.route("/invoice/customer")
@login_required
def invoice_customer_new():
    """Show the blank customer / shipment invoice form."""
    cdb = get_cdb()
    company_id = get_current_company()
    clients = cdb.query(Client).filter(
        Client.company_id == company_id,
        ~Client.client_type.in_(["Supplier", "Both"])  # Exclude suppliers
    ).all()

    price_lists = cdb.query(PriceList).filter_by(
        company_id=company_id, 
        is_active=True
    ).all()

    # Auto-generate invoice ID
    cust_count = (
        cdb.query(Invoice)
        .filter_by(company_id=company_id)
        .filter(Invoice.invoice_id.like("CUST-%"))
        .count()
    )
    invoice_id = f"CUST-{datetime.now().strftime('%Y%m%d')}-{cust_count + 1:03d}"
    docket_no  = _next_awb_number(company_id)

    return render_template(
        "invoice.html",
        clients=clients,
        invoice_id=invoice_id,
        docket_no=docket_no,
        today=str(date.today()),
        form_data={},
        stock_items_json=json.dumps([{
            "code":     s.code,
            "name":     s.name,
            "unit":     s.unit or "pcs",
            "quantity": s.quantity,
        } for s in cdb.query(StockItem).filter_by(company_id=company_id).order_by(StockItem.name).all()]),
        price_lists=price_lists
    )


@app.route("/invoice/customer/save", methods=["POST"])
@login_required
def invoice_customer_save():
    """Save a customer / shipment invoice submitted from invoice.html."""
    cdb = get_cdb()
    company_id = get_current_company()

    # ── Basic fields ──────────────────────────────────────────────────────────
    client_id_raw  = request.form.get("customer_id")
    client_id      = int(client_id_raw) if client_id_raw else None
    invoice_date   = request.form.get("invoice_date") or str(date.today())
    docket_no      = request.form.get("docket_no", "")
    action         = request.form.get("action", "final")

    # ── Charges & totals ──────────────────────────────────────────────────────
    freight        = float(request.form.get("freight_amount", 0) or 0)
    fuel           = float(request.form.get("fuel_surcharge",  0) or 0)
    other          = float(request.form.get("other_charges",   0) or 0)
    base           = freight + fuel + other
    co             = Company.query.filter_by(company_id=company_id).first()
    apply_gst      = co.is_gst_registered if (co and hasattr(co, 'is_gst_registered')) else True
    gst            = round(base * 0.18, 2) if apply_gst else 0.0
    grand_total    = round(base + gst, 2)
    amount_paid    = float(request.form.get("amount_paid", 0) or 0)
    balance        = round(grand_total - amount_paid, 2)

    # ── Payment info ─────────────────────────────────────────────────────────
    payment_mode   = request.form.get("payment_mode", "cash")
    upi_app        = request.form.get("upi_app", "")
    upi_ref        = request.form.get("upi_ref", "")
    cheque_no      = request.form.get("cheque_no", "")
    cheque_date    = request.form.get("cheque_date", "")
    cheque_bank    = request.form.get("cheque_bank", "")

    # ── Resale Charges ──────────────────────────────────────────────────────────
    has_resale = request.form.get("resale_active") == "true"
    resale_amount = float(request.form.get("resale_amount", 0) or 0)
    resale_reason = request.form.get("resale_reason", "").strip()
    resale_date_str = request.form.get("resale_date")
    resale_notes = request.form.get("resale_notes", "").strip()
    
    # Apply GST to resale charges
    if has_resale and resale_amount > 0:
        co = Company.query.filter_by(company_id=company_id).first()
        apply_gst = co.is_gst_registered if (co and hasattr(co, 'is_gst_registered')) else True
        resale_gst = round(resale_amount * 0.18, 2) if apply_gst else 0.0
        
        # Add resale to totals - UPDATE the existing totals
        base = freight + fuel + other + resale_amount
        gst = round(base * 0.18, 2) if apply_gst else 0.0
        grand_total = round(base + gst, 2)
        balance = round(grand_total - amount_paid, 2)
        
        resale_date = date.fromisoformat(resale_date_str) if resale_date_str else date.today()
    else:
        resale_amount = 0
        resale_gst = 0
        resale_date = None
        resale_reason = None
        resale_notes = None

    # ── Status ────────────────────────────────────────────────────────────────
    if action == "draft":
        status = "Draft"
    elif balance <= 0:
        status = "Paid"
    elif amount_paid > 0:
        status = "Partial"
    else:
        status = "Draft"

    # ── Generate invoice ID ───────────────────────────────────────────────────
    cust_count = (
        cdb.query(Invoice)
        .filter_by(company_id=company_id)
        .filter(Invoice.invoice_id.like("CUST-%"))
        .count()
    )
    invoice_id = f"CUST-{datetime.now().strftime('%Y%m%d')}-{cust_count + 1:03d}"

    # ── Shipment / receiver details stored in notes / terms ──────────────────
    notes = request.form.get("notes", "")
    
    # ── Process Packages - ADD TO INVENTORY AND CREATE INVOICE ITEMS ──────────
    pkg_names = request.form.getlist("pkg_name[]")
    pkg_types = request.form.getlist("pkg_type[]")
    pkg_qtys  = request.form.getlist("pkg_qty[]")
    pkg_l     = request.form.getlist("pkg_l[]")
    pkg_w     = request.form.getlist("pkg_w[]")
    pkg_h     = request.form.getlist("pkg_h[]")
    pkg_wt    = request.form.getlist("pkg_wt[]")
    pkg_rates = request.form.getlist("pkg_rate[]")
    
    stock_added = []
    stock_warnings = []
    invoice_items_data = []  # Store for creating InvoiceItem records
    
    for i in range(len(pkg_names)):
        item_name = (pkg_names[i] or "").strip()
        if not item_name:
            continue

        qty      = float(pkg_qtys[i] or 1) if pkg_qtys[i] else 1
        rate     = float(pkg_rates[i] or 0) if pkg_rates[i] else 0
        pkg_type = (pkg_types[i] if i < len(pkg_types) else "Box") or "Box"

        # Match by name + client_id so each party gets their own row
        existing_item = cdb.query(StockItem).filter_by(
            company_id=company_id,
            name=item_name,
            client_id=client_id,
        ).first()

        if existing_item:
            existing_item.quantity   += qty
            existing_item.last_updated = date.today()
            if rate > 0:
                existing_item.unit_price   = rate
                existing_item.purchase_rate = rate
            cdb.add(StockPurchaseHistory(
                stock_item_id=existing_item.id,
                purchase_invoice_id=None,
                quantity=qty,
                purchase_rate=rate,
                gst_percent=existing_item.gst_percent or 0,
                purchase_date=date.fromisoformat(invoice_date),
            ))
        else:
            stock_count = cdb.query(StockItem).filter_by(company_id=company_id).count()
            new_code = f"PKG-{stock_count + 1:03d}"
            new_item = StockItem(
                company_id    = company_id,
                code          = f"PKG-{stock_count + 1:03d}",
                name          = item_name,
                category      = "Packaging",
                item_type     = pkg_type,
                client_id     = client_id,          # ← party ownership
                quantity      = qty,
                unit          = "pcs",
                unit_price    = rate,
                purchase_rate = rate,
                reorder_level = 0,
                gst_percent   = 18,
                hsn           = "",
                last_updated  = date.today(),
            )
            cdb.add(new_item)
            cdb.flush()
            cdb.add(StockPurchaseHistory(
                stock_item_id=new_item.id,
                purchase_invoice_id=None,
                quantity=qty,
                purchase_rate=rate,
                gst_percent=18,
                purchase_date=date.fromisoformat(invoice_date),
            ))
            #cdb.add(movement)
            stock_added.append(f"{qty}× {item_name} (new stock item {new_code})")
            stock_item_id = new_item.id
        
        # Store invoice item data for later creation
        invoice_items_data.append({
            'stock_item_id': stock_item_id,
            'description': item_name,
            'qty': qty,
            'rate': rate,
            'discount': 0
        })
    
    # Collect package data for JSON storage
    packages_data = []
    for i in range(len(pkg_names)):
        if pkg_names[i] and pkg_names[i].strip():
            packages_data.append({
                "name": pkg_names[i],
                "type": pkg_types[i] if i < len(pkg_types) else "",
                "qty": float(pkg_qtys[i] or 1) if pkg_qtys[i] else 1,
                "length": float(pkg_l[i] or 0) if i < len(pkg_l) else 0,
                "width": float(pkg_w[i] or 0) if i < len(pkg_w) else 0,
                "height": float(pkg_h[i] or 0) if i < len(pkg_h) else 0,
                "weight": float(pkg_wt[i] or 0) if i < len(pkg_wt) else 0,
                "rate": float(pkg_rates[i] or 0) if i < len(pkg_rates) else 0,
            })
    
    # Pack all extra shipment metadata into the terms field as JSON
    shipment_meta = json.dumps({
        "docket_no":        docket_no,
        "shipper_name":     request.form.get("shipper_name", ""),
        "shipper_address1": request.form.get("shipper_address1", ""),
        "shipper_address2": request.form.get("shipper_address2", ""),
        "shipper_city": request.form.get("shipper_city", ""),
        "shipper_state": request.form.get("shipper_state", ""),
        "shipper_pincode": request.form.get("shipper_pincode", ""),
        "shipper_country": request.form.get("shipper_country", "India"),
        "receiver_name": request.form.get("receiver_name", ""),
        "receiver_phone": request.form.get("receiver_phone", ""),
        "receiver_address1": request.form.get("receiver_address1", ""),
        "receiver_address2": request.form.get("receiver_address2", ""),
        "receiver_city": request.form.get("receiver_city", ""),
        "receiver_state": request.form.get("receiver_state", ""),
        "receiver_pincode": request.form.get("receiver_pincode", ""),
        "receiver_country": request.form.get("receiver_country", "India"),
        "destination":      request.form.get("destination", ""),
        "shipment_type":    request.form.get("shipment_type", ""),
        "mode":             request.form.get("mode", ""),
        "carrier":          request.form.get("carrier", ""),
        "carrier_ref":      request.form.get("carrier_ref", ""),
        "origin":           request.form.get("origin", "India"),
        "pickup_date":      request.form.get("pickup_date", ""),
        "departure_time":   request.form.get("departure_time", ""),
        "expected_delivery":request.form.get("expected_delivery", ""),
        "comments":         request.form.get("comments", ""),
        "payment_mode":     payment_mode,
        "upi_app":          upi_app,
        "upi_ref":          upi_ref,
        "cheque_no":        cheque_no,
        "cheque_date":      cheque_date,
        "cheque_bank":      cheque_bank,
        "freight":          freight,
        "fuel":             fuel,
        "other":            other,
        "gst":              gst,
        "amount_paid":      amount_paid,
        "packages":         packages_data,
        "resale": {
        "amount": resale_amount,
        "gst": resale_gst if has_resale else 0,
        "reason": resale_reason,
        "date": resale_date.strftime("%Y-%m-%d") if resale_date else "",
        "notes": resale_notes,
        "added_by": get_current_user().get("email")
    } if has_resale and resale_amount > 0 else None
    })

    # CREATE INVOICE
    inv = Invoice(
        invoice_id     = invoice_id,
        company_id     = company_id,
        client_id      = client_id,
        date           = date.fromisoformat(invoice_date),
        status         = status,
        contact_person = request.form.get("shipper_name", ""),
        phone          = request.form.get("customer_phone", ""),
        subtotal       = base,
        tax_amount     = gst,
        grand_total    = grand_total,
        terms          = shipment_meta,
        email          = notes,
        paid_amount    = amount_paid,
        balance        = balance,
    )
    cdb.add(inv)
    cdb.flush()  # Get the invoice ID

    # CREATE INVOICE ITEMS (THIS IS WHAT WAS MISSING!)
    for item_data in invoice_items_data:
        inv_item = InvoiceItem(
            invoice_id    = inv.id,
            stock_item_id = item_data['stock_item_id'],
            code          = f"PKG-{item_data['stock_item_id']}",
            description   = item_data['description'],
            qty           = item_data['qty'],
            rate          = item_data['rate'],
            discount      = item_data['discount']
        )
        cdb.add(inv_item)

    # ── RECORD PAYMENT IN CASH IN HAND OR BANK ACCOUNT ──────────────────────────
    if amount_paid > 0:
        transaction_date = date.fromisoformat(invoice_date)
        
        if payment_mode == "cash":
            cash_txn = CashTransaction(
                company_id=company_id,
                type="income",
                date=transaction_date,
                category="Sales",
                description=f"Payment received for invoice {invoice_id} - Customer Invoice",
                amount=amount_paid,
                reference=invoice_id,
                notes=f"Payment via Cash from customer",
                created_by=get_current_user().get("email")
            )
            cdb.add(cash_txn)
        elif payment_mode == "online":
            bank_account = cdb.query(BankAccount).filter_by(
                company_id=company_id, 
                status='Active'
            ).first()
            if not bank_account:
                bank_account = BankAccount(
                    company_id=company_id,
                    bank_name="Default Bank Account",
                    account_name="Sales Receipts",
                    account_number="SALES001",
                    ifsc_code="DEFAULT0001",
                    branch="Main Branch",
                    opening_balance=0,
                    balance=amount_paid,
                    status='Active',
                    created_at=datetime.utcnow()
                )
                cdb.add(bank_account)
                cdb.flush()
            else:
                bank_account.balance += amount_paid
                bank_account.updated_at = datetime.utcnow()
            
            bank_txn = BankTransaction(
                bank_account_id=bank_account.id,
                company_id=company_id,
                type="credit",
                date=transaction_date,
                description=f"Payment received for invoice {invoice_id} - via {upi_app or 'Online'}",
                amount=amount_paid,
                reference=upi_ref or invoice_id,
                transaction_mode="Online",
                notes=f"UPI App: {upi_app}, Ref: {upi_ref}",
                created_by=get_current_user().get("email")
            )
            cdb.add(bank_txn)
        elif payment_mode == "cheque":
            bank_account = cdb.query(BankAccount).filter_by(
                company_id=company_id, 
                status='Active'
            ).first()
            if not bank_account:
                bank_account = BankAccount(
                    company_id=company_id,
                    bank_name=cheque_bank or "Cheque Account",
                    account_name="Cheque Receipts",
                    account_number="CHEQ001",
                    ifsc_code="CHEQ0001",
                    branch="Main Branch",
                    opening_balance=0,
                    balance=amount_paid,
                    status='Active',
                    created_at=datetime.utcnow()
                )
                cdb.add(bank_account)
                cdb.flush()
            else:
                bank_account.balance += amount_paid
                bank_account.updated_at = datetime.utcnow()
            
            bank_txn = BankTransaction(
                bank_account_id=bank_account.id,
                company_id=company_id,
                type="credit",
                date=transaction_date,
                description=f"Cheque payment received for invoice {invoice_id}",
                amount=amount_paid,
                reference=cheque_no or invoice_id,
                transaction_mode="Cheque",
                notes=f"Cheque No: {cheque_no}, Bank: {cheque_bank}, Date: {cheque_date}",
                created_by=get_current_user().get("email")
            )
            cdb.add(bank_txn)

    # ── Update client pending balance if credit / unpaid ──────────────────────
    if balance > 0 and client_id:
        client = cdb.query(Client).filter_by(id=client_id, company_id=company_id).first()
        if client and hasattr(client, "pending"):
            client.pending = (client.pending or 0) + balance

    cdb.commit()

    # ── Build flash message ───────────────────────────────────────────────────
    msg = f"Customer invoice {invoice_id} (AWB: {docket_no}) saved successfully!"
    if stock_added:
        msg += f" Stock added: {', '.join(stock_added)}."
    if amount_paid > 0:
        msg += f" Payment of ₹{amount_paid:,.2f} recorded via {payment_mode}."
    if balance > 0:
        msg += f" Balance of ₹{balance:,.2f} added to debtors."

    flash(msg)
    return redirect(url_for("invoice_list"))

@app.route("/api/suppliers/list")
@login_required
def api_suppliers_list():
    cdb = get_cdb()
    company_id = get_current_company()
    suppliers = cdb.query(Client).filter(
        Client.company_id == company_id,
        Client.client_type.in_(["Supplier", "Both"])
    ).order_by(Client.name).all()
    
    return jsonify([{
        "id": s.id,
        "name": s.name,
        "gst": s.gst_number or ""
    } for s in suppliers])


# ── Suppliers ─────────────────────────────────────────────────────────────────
# Add this block in app.py right after client_delete() and before the Stock section.
# Also add  Supplier  to the customer_models import line at the top of app.py.
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_supplier(s):
    """Return a dict whose keys match what suppliers.html / supplier_form.html expect."""
    return {
        "id":              s.id,
        "supplier_name":   s.name,
        "supplier_type":   s.supplier_type   or "Business",
        "contact_person":  s.contact_person  or "",
        "phone":           s.phone           or "",
        "alternate_phone": s.alternate_phone or "",
        "email":           s.email           or "",
        "website":         s.website         or "",
        "address_line1":   s.address_line1   or "",
        "address_line2":   s.address_line2   or "",
        "city":            s.city            or "",
        "state":           s.state           or "",
        "pincode":         s.pincode         or "",
        "country":         s.country         or "India",
        "gst_number":      s.gst_number      or "",
        "pan_number":      s.pan_number      or "",
        "gst_type":        s.gst_type        or "Regular",
        "credit_limit":    s.credit_limit    or 0.0,
        "credit_days":     s.credit_days     or 30,
        "payable":         s.payable         or 0.0,   # ← payable, NOT outstanding
        "opening_balance": s.opening_balance or 0.0,
        "last_purchase":   s.last_purchase,
        "status":          s.status          or "Active",
        "notes":           s.notes           or "",
        "created_at":      s.created_at,
    }


@app.route("/suppliers")
@login_required
def supplier_list():
    cdb           = get_cdb()
    company_id    = get_current_company()
    filter_status = request.args.get("status", "All")

    query = cdb.query(Supplier).filter_by(company_id=company_id)
    if filter_status != "All":
        query = query.filter_by(status=filter_status)

    suppliers = [_normalize_supplier(s) for s in query.all()]
    return render_template("suppliers.html", suppliers=suppliers, current_status=filter_status)


@app.route("/suppliers/new", methods=["GET", "POST"])
@login_required
def supplier_new():
    cdb        = get_cdb()
    company_id = get_current_company()
    if request.method == "POST":
        f   = request.form
        gst = f.get("gst_number", "").strip().upper()

        if gst:
            existing_gst = cdb.query(Supplier).filter_by(
                company_id=company_id, gst_number=gst
            ).first()
            if existing_gst:
                flash(f"GST number {gst} is already registered to supplier '{existing_gst.name}'. Please check and try again.", "error")
                return render_template("supplier_form.html", form_data=f)

        new_supplier = Supplier(
            company_id      = company_id,
            name            = f.get("supplier_name", "").strip(),
            supplier_type   = f.get("supplier_type", "Business"),
            contact_person  = f.get("contact_person", "").strip(),
            phone           = f.get("phone", "").strip(),
            alternate_phone = f.get("alternate_phone", "").strip(),
            email           = f.get("email", "").strip().lower(),
            website         = f.get("website", "").strip(),
            address_line1   = f.get("address_line1", "").strip(),
            address_line2   = f.get("address_line2", "").strip(),
            city            = f.get("city", "").strip(),
            state           = f.get("state", "").strip(),
            pincode         = f.get("pincode", "").strip(),
            country         = f.get("country", "India").strip(),
            gst_number      = gst or None,
            pan_number      = f.get("pan_number", "").strip().upper() or None,
            gst_type        = f.get("gst_type", "Regular"),
            credit_limit    = float(f.get("credit_limit", 0) or 0),
            credit_days     = int(f.get("credit_days", 30) or 30),
            payable         = float(f.get("opening_balance", 0) or 0),
            opening_balance = float(f.get("opening_balance", 0) or 0),
            status          = f.get("status", "Active"),
            notes           = f.get("notes", "").strip(),
            created_at      = date.today(),
        )
        cdb.add(new_supplier)
        cdb.commit()
        flash(f"Supplier '{new_supplier.name}' added successfully!")
        return redirect(url_for("supplier_list"))
    return render_template("supplier_form.html", form_data={})


@app.route("/suppliers/<int:supplier_pk>")
@login_required
def supplier_view(supplier_pk):
    cdb        = get_cdb()
    company_id = get_current_company()
    s          = _first_or_404(cdb.query(Supplier).filter_by(id=supplier_pk, company_id=company_id).first())
    supplier   = _normalize_supplier(s)
    purchases  = cdb.query(PurchaseInvoice).filter_by(company_id=company_id, supplier_id=s.id).order_by(PurchaseInvoice.date.desc()).all()
    return render_template("supplier_detail.html", supplier=supplier, purchases=purchases)


@app.route("/suppliers/<int:supplier_pk>/edit", methods=["GET", "POST"])
@login_required
def supplier_edit(supplier_pk):
    cdb        = get_cdb()
    company_id = get_current_company()
    s          = _first_or_404(cdb.query(Supplier).filter_by(id=supplier_pk, company_id=company_id).first())
    if request.method == "POST":
        f   = request.form
        gst = f.get("gst_number", "").strip().upper()

        if gst:
            existing_gst = cdb.query(Supplier).filter(
                Supplier.company_id == company_id,
                Supplier.gst_number == gst,
                Supplier.id != s.id
            ).first()
            if existing_gst:
                flash(f"GST number {gst} is already registered to supplier '{existing_gst.name}'.", "error")
                return render_template("supplier_form.html", supplier=_normalize_supplier(s), form_data=f)

        s.name            = f.get("supplier_name",   s.name).strip()
        s.supplier_type   = f.get("supplier_type",   s.supplier_type)
        s.contact_person  = f.get("contact_person",  s.contact_person  or "").strip()
        s.phone           = f.get("phone",            s.phone           or "").strip()
        s.alternate_phone = f.get("alternate_phone",  s.alternate_phone or "").strip()
        s.email           = f.get("email",            s.email           or "").strip().lower()
        s.website         = f.get("website",          s.website         or "").strip()
        s.address_line1   = f.get("address_line1",    s.address_line1   or "").strip()
        s.address_line2   = f.get("address_line2",    s.address_line2   or "").strip()
        s.city            = f.get("city",             s.city            or "").strip()
        s.state           = f.get("state",            s.state           or "").strip()
        s.pincode         = f.get("pincode",          s.pincode         or "").strip()
        s.country         = f.get("country",          s.country         or "India").strip()
        s.gst_number      = gst or None
        s.pan_number      = f.get("pan_number",       s.pan_number      or "").strip().upper() or None
        s.gst_type        = f.get("gst_type",         s.gst_type)
        s.credit_limit    = float(f.get("credit_limit",    s.credit_limit    or 0) or 0)
        s.credit_days     = int(f.get("credit_days",       s.credit_days     or 30) or 30)
        s.opening_balance = float(f.get("opening_balance", s.opening_balance or 0) or 0)
        s.status          = f.get("status", s.status)
        s.notes           = f.get("notes",  s.notes or "").strip()
        cdb.commit()
        flash(f"Supplier '{s.name}' updated successfully!")
        return redirect(url_for("supplier_list"))
    return render_template("supplier_form.html", supplier=_normalize_supplier(s), form_data={})


@app.route("/suppliers/<int:supplier_pk>/delete", methods=["GET", "POST"])
@login_required
def supplier_delete(supplier_pk):
    cdb        = get_cdb()
    company_id = get_current_company()
    s          = _first_or_404(cdb.query(Supplier).filter_by(id=supplier_pk, company_id=company_id).first())
    cdb.delete(s)
    cdb.commit()
    flash("Supplier deleted.")
    return redirect(url_for("supplier_list"))

@app.route("/api/customers/list")
@login_required
def api_customers_list():
    """Return list of customers (non-supplier clients) for the purchase form dropdown."""
    cdb = get_cdb()
    company_id = get_current_company()
    customers = cdb.query(Client).filter(
        Client.company_id == company_id,
        ~Client.client_type.in_(["Supplier", "Both"])
    ).filter(Client.status == "Active").order_by(Client.name).all()

    return jsonify([{
        "id":       c.id,
        "name":     c.name,
        "phone":    c.phone or "",
        "email":    c.email or "",
        "city":     c.city or "",
        "gst":      c.gst_number or "",
        "address":  c.address_line1 or "",
    } for c in customers])

@app.route("/api/stock/items/by-client/<int:client_id>")
@login_required
def api_stock_items_by_client(client_id):
    """Return stock items that have been previously invoiced to a specific client.
    If no history found, returns ALL stock items."""
    cdb = get_cdb()
    company_id = get_current_company()

    # Find all stock item IDs that appear in invoices for this client
    linked_stock_ids = db.session.query(InvoiceItem.stock_item_id).join(
        Invoice, InvoiceItem.invoice_id == Invoice.id
    ).filter(
        Invoice.company_id == company_id,
        Invoice.client_id  == client_id,
        InvoiceItem.stock_item_id.isnot(None)
    ).distinct().all()

    stock_ids = [row[0] for row in linked_stock_ids if row[0] is not None]

    if not stock_ids:
        # No history - return ALL stock items
        items = cdb.query(StockItem).filter_by(company_id=company_id).order_by(StockItem.name).all()
    else:
        items = cdb.query(StockItem).filter(
            StockItem.company_id == company_id,
            StockItem.id.in_(stock_ids)
        ).order_by(StockItem.name).all()

    return jsonify([{
        "id":            item.id,
        "code":          item.code or "",
        "name":          item.name,
        "unit":          item.unit or "pcs",
        "quantity":      item.quantity,
        "unit_price":    float(item.unit_price or 0),
        "purchase_rate": float(item.purchase_rate or item.last_purchase_rate or 0),
        "gst_percent":   float(item.gst_percent or 18),
        "hsn":           item.hsn or "",
        "category":      item.category or "",
    } for item in items])


# ─────────────────────────────────────────────────────────────────────────────
# ── Shipper Invoice (estimate.html) ──────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

"""def _get_available_dockets(company_id):
    
    used_invoice_ids = set()
    shipper_estimates = cdb.query(Estimate).filter_by(company_id=company_id).all()
    for est in shipper_estimates:
        if est.terms:
            try:
                t = json.loads(est.terms)
                lid = t.get("linked_invoice_id", "")
                if lid:
                    used_invoice_ids.add(lid)
            except (ValueError, TypeError):
                pass

    all_cust = cdb.query(Invoice).filter_by(company_id=company_id).filter(Invoice.invoice_id.like("CUST-%")).order_by(Invoice.date.desc()).all()

    dockets = []
    for inv in all_cust:
        if inv.invoice_id in used_invoice_ids:
            continue
        meta = {}
        if inv.terms:
            try:
                meta = json.loads(inv.terms)
            except (ValueError, TypeError):
                pass
        docket_no = meta.get("docket_no", "")
        if not docket_no:
            continue
        cname = inv.client_obj.name if inv.client_obj else (inv.contact_person or inv.invoice_id)
        dockets.append({
            "invoice_id": inv.invoice_id,
            "docket_no": docket_no,
            "customer_name": cname,
        })
    return dockets"""
def _get_available_dockets(company_id, exclude_estimate_id=None):
    """Return customer invoices that have NOT yet had a Shipper Invoice generated.
    If exclude_estimate_id is provided, include that invoice's docket even if used."""
    cdb = get_cdb()
    used_invoice_ids = set()
    shipper_estimates = cdb.query(Estimate).filter_by(company_id=company_id).all()
    
    for est in shipper_estimates:
        # Skip the current estimate being edited
        if exclude_estimate_id and est.estimate_id == exclude_estimate_id:
            continue
        if est.terms:
            try:
                t = json.loads(est.terms)
                lid = t.get("linked_invoice_id", "")
                if lid:
                    used_invoice_ids.add(lid)
            except (ValueError, TypeError):
                pass

    all_cust = cdb.query(Invoice).filter_by(company_id=company_id).filter(Invoice.invoice_id.like("CUST-%")).order_by(Invoice.date.desc()).all()

    dockets = []
    for inv in all_cust:
        if inv.invoice_id in used_invoice_ids:
            continue
        meta = {}
        if inv.terms:
            try:
                meta = json.loads(inv.terms)
            except (ValueError, TypeError):
                pass
        docket_no = meta.get("docket_no", "")
        if not docket_no:
            continue
        cname = inv.client_obj.name if inv.client_obj else (inv.contact_person or inv.invoice_id)
        dockets.append({
            "invoice_id": inv.invoice_id,
            "docket_no": docket_no,
            "customer_name": cname,
        })
    return dockets

@app.route("/api/docket-info/<docket_no>")
@login_required
def api_docket_info(docket_no):
    """Return sender/receiver details for a given AWB/docket number."""
    cdb = get_cdb()
    company_id = get_current_company()
    all_cust = cdb.query(Invoice).filter_by(company_id=company_id).filter(Invoice.invoice_id.like("CUST-%")).all()
    for inv in all_cust:
        meta = {}
        if inv.terms:
            try:
                meta = json.loads(inv.terms)
            except (ValueError, TypeError):
                pass
        if meta.get("docket_no", "") == docket_no:
            cname = inv.client_obj.name if inv.client_obj else (inv.contact_person or "")
            cphone = inv.client_obj.phone if inv.client_obj else (inv.phone or "")
            return jsonify({
                "invoice_id": inv.invoice_id,
                "client_id": inv.client_id,
                "shipper_name": meta.get("shipper_name", cname),
                "shipper_phone": meta.get("shipper_phone", cphone),
                "shipper_address": meta.get("shipper_address", ""),
                "receiver_name": meta.get("receiver_name", ""),
                "receiver_phone": meta.get("receiver_phone", ""),
                "receiver_address": meta.get("receiver_address", ""),
                "destination": meta.get("destination", ""),
                "shipment_type": meta.get("shipment_type", ""),
                "mode": meta.get("mode", ""),
                "carrier": meta.get("carrier", ""),
            })
    return jsonify({"error": "not found"}), 404






@login_required
@app.route("/estimate/list")
@login_required
def estimate_list():
    cdb = get_cdb()
    company_id    = get_current_company()
    filter_status = request.args.get("status", "All")
    query         = cdb.query(Estimate).filter_by(company_id=company_id)
    if filter_status != "All":
        query = query.filter_by(status=filter_status)
    raw = query.order_by(Estimate.date.desc()).all()

    estimates = []
    for est in raw:
        meta = {}
        if est.terms:
            try:
                meta = json.loads(est.terms)
            except (ValueError, TypeError):
                meta = {}
        estimates.append({
            "id":            est.estimate_id,
            "date":          est.date.strftime("%d %b %Y") if est.date else "—",
            "valid_until":   est.valid_until.strftime("%d %b %Y") if est.valid_until else "—",
            "status":        est.status or "Draft",
            "grand_total":   est.grand_total or 0,
            "subtotal":      est.subtotal or 0,
            "tax_amount":    est.tax_amount or 0,
            "client_name":   est.client_obj.name if est.client_obj else (est.contact_person or "—"),
            "phone":         est.phone or "",
            "docket_no":     meta.get("docket_no", ""),
            "receiver_name": meta.get("receiver_name", ""),
            "destination":   meta.get("destination", ""),
            "shipment_type": meta.get("shipment_type", ""),
            "mode":          meta.get("mode", ""),
            "is_shipper":    bool(meta.get("docket_no", "") or est.estimate_id.startswith("SHIP-")),
            "reference": meta.get("reference", meta.get("aadhar", "")),
        })

    return render_template("estimate_list.html", estimates=estimates, current_status=filter_status)



"""@app.route("/estimate/new", methods=["GET", "POST"])
@login_required
def estimate_new():
    cdb = get_cdb()
    company_id = get_current_company()
    clients    = cdb.query(Client).filter_by(company_id=company_id).all()

    edit_id  = request.args.get("edit")
    existing = cdb.query(Estimate).filter_by(estimate_id=edit_id, company_id=company_id).first() if edit_id else None

    if request.method == "POST":
        item_codes   = request.form.getlist("item_code[]")
        descriptions = request.form.getlist("description[]")
        qtys         = request.form.getlist("qty[]")
        rates        = request.form.getlist("rate[]")
        discounts    = request.form.getlist("discount[]")

        subtotal   = 0
        line_items = []
        for i in range(len(descriptions)):
            if descriptions[i] and descriptions[i].strip():
                qty  = float(qtys[i])  if qtys[i]  else 0
                rate = float(rates[i]) if rates[i] else 0
                disc = float(discounts[i]) if discounts[i] else 0
                subtotal += qty * rate * (1 - disc / 100)
                line_items.append((item_codes[i], descriptions[i], qty, rate, disc))

        tax         = subtotal * 0.18
        grand_total = subtotal + tax

        client_id_raw = request.form.get("client_id")
        client_id     = int(client_id_raw) if client_id_raw else None

        if existing:
            existing.client_id      = client_id
            existing.date           = date.fromisoformat(request.form.get("estimate_date") or str(date.today()))
            existing.valid_until    = date.fromisoformat(request.form.get("valid_until")) if request.form.get("valid_until") else None
            existing.status         = request.form.get("status", "Draft")
            existing.contact_person = request.form.get("contact_person", "")
            existing.email          = request.form.get("email", "")
            existing.phone          = request.form.get("phone", "")
            existing.subtotal       = subtotal
            existing.tax_amount     = tax
            existing.grand_total    = grand_total
            existing.terms          = request.form.get("terms", "")
            cdb.query(EstimateItem).filter_by(estimate_id=existing.id).delete()
            for code, desc, qty, rate, disc in line_items:
                si = cdb.query(StockItem).filter_by(company_id=company_id, code=code.upper()).first()
                cdb.add(EstimateItem(
                    estimate_id=existing.id,
                    stock_item_id=si.id if si else None,
                    code=code, description=desc, qty=qty, rate=rate, discount=disc,
                ))
            cdb.commit()
            flash(f"Estimate {existing.estimate_id} updated!")
        else:
            est_count   = cdb.query(Estimate).count()
            estimate_id = f"EST-{datetime.now().strftime('%Y%m%d')}-{est_count+1:03d}"
            est         = Estimate(
                estimate_id=estimate_id, company_id=company_id,
                client_id=client_id,
                date=date.fromisoformat(request.form.get("estimate_date") or str(date.today())),
                valid_until=date.fromisoformat(request.form.get("valid_until")) if request.form.get("valid_until") else None,
                status=request.form.get("status", "Draft"),
                contact_person=request.form.get("contact_person", ""),
                email=request.form.get("email", ""),
                phone=request.form.get("phone", ""),
                subtotal=subtotal, tax_amount=tax, grand_total=grand_total,
                terms=request.form.get("terms", ""),
            )
            cdb.add(est)
            cdb.flush()
            for code, desc, qty, rate, disc in line_items:
                si = cdb.query(StockItem).filter_by(company_id=company_id, code=code.upper()).first()
                cdb.add(EstimateItem(
                    estimate_id=est.id,
                    stock_item_id=si.id if si else None,
                    code=code, description=desc, qty=qty, rate=rate, discount=disc,
                ))
            cdb.commit()
            flash(f"Estimate {estimate_id} created!")

        return redirect(url_for("estimate_list"))

    valid_until = str(date.today() + timedelta(days=30))
    available_dockets = _get_available_dockets(company_id)

    # Auto-generate Shipper Invoice ID for display
    ship_count = cdb.query(Estimate).filter_by(company_id=company_id).count()
    shipper_invoice_id = f"SHIP-{datetime.now().strftime('%Y%m%d')}-{ship_count + 1:03d}"

    return render_template("estimate.html",
                       clients=clients, estimate=existing,
                       today=str(date.today()), valid_until=valid_until,
                       form_data={},
                       available_dockets=available_dockets,
                       shipper_invoice_id=shipper_invoice_id)"""

@app.route("/estimate/new", methods=["GET", "POST"])
@login_required
def estimate_new():
    cdb = get_cdb()
    company_id = get_current_company()
    clients = cdb.query(Client).filter_by(company_id=company_id).all()

    edit_id = request.args.get("edit")
    existing = cdb.query(Estimate).filter_by(estimate_id=edit_id, company_id=company_id).first() if edit_id else None

    # Handle POST (Save)
    if request.method == "POST":
        descriptions = request.form.getlist("description[]")
        hs_codes = request.form.getlist("hs_code[]")
        units = request.form.getlist("unit[]")
        qtys = request.form.getlist("qty[]")
        rates = request.form.getlist("rate[]")

        subtotal = 0
        line_items = []
        for i in range(len(descriptions)):
            if descriptions[i] and descriptions[i].strip():
                qty = float(qtys[i]) if qtys[i] else 0
                rate = float(rates[i]) if rates[i] else 0
                subtotal += qty * rate
                line_items.append({
                    "description": descriptions[i],
                    "hs_code": hs_codes[i] if i < len(hs_codes) else "",
                    "unit": units[i] if i < len(units) else "Pc",
                    "qty": qty,
                    "rate": rate,
                })

        grand_total = subtotal
        amount_paid = float(request.form.get("amount_paid", 0) or 0)
        balance = round(grand_total - amount_paid, 2)

        action = request.form.get("action", "final")
        if action == "draft":
            status = "Draft"
        elif balance <= 0:
            status = "Paid"
        elif amount_paid > 0:
            status = "Partial"
        else:
            status = "Unpaid"

        client_id_raw = request.form.get("shipper_id")
        client_id = int(client_id_raw) if client_id_raw else None

        # Pack metadata into terms
        terms_data = json.dumps({
            "docket_no": request.form.get("docket_no", ""),
            "linked_invoice_id": request.form.get("linked_invoice_id", ""),
            "shipper_name": request.form.get("shipper_name", ""),
            "shipper_phone": request.form.get("shipper_phone", ""),
            "shipper_address": request.form.get("shipper_address", ""),
            "receiver_name": request.form.get("receiver_name", ""),
            "receiver_phone": request.form.get("receiver_phone", ""),
            "receiver_company": request.form.get("receiver_company", ""),
            "receiver_address": request.form.get("receiver_address", ""),
            "destination": request.form.get("destination", ""),
            "payment_mode": request.form.get("payment_mode", "credit"),
            "upi_app": request.form.get("upi_app", ""),
            "upi_ref": request.form.get("upi_ref", ""),
            "cheque_no": request.form.get("cheque_no", ""),
            "cheque_date": request.form.get("cheque_date", ""),
            "cheque_bank": request.form.get("cheque_bank", ""),
            "weight": request.form.get("weight", "0.00"),
            "reference": request.form.get("reference", ""),
            "amount_paid": amount_paid,
            "balance": balance,
            "line_items": line_items,
        })

        edit_invoice_id = request.form.get("edit_invoice_id", "").strip()
        existing_edit = cdb.query(Estimate).filter_by(estimate_id=edit_invoice_id, company_id=company_id).first() if edit_invoice_id else None

        if existing_edit:
            # Update existing
            existing_edit.client_id = client_id
            existing_edit.date = date.fromisoformat(request.form.get("invoice_date") or str(date.today()))
            existing_edit.status = status
            existing_edit.contact_person = request.form.get("shipper_name", "")
            existing_edit.email = request.form.get("notes", "")
            existing_edit.phone = request.form.get("shipper_phone", "")
            existing_edit.subtotal = subtotal
            existing_edit.tax_amount = 0
            existing_edit.grand_total = grand_total
            existing_edit.terms = terms_data

            # Replace items
            cdb.query(EstimateItem).filter_by(estimate_id=existing_edit.id).delete()
            for item in line_items:
                cdb.add(EstimateItem(
                    estimate_id=existing_edit.id,
                    description=item["description"],
                    hs_code=item.get("hs_code", ""),
                    unit=item.get("unit", "Pc"),
                    qty=item["qty"],
                    rate=item["rate"],
                    discount=0,
                ))
            
            cdb.commit()
            flash(f"Shipper Invoice {existing_edit.estimate_id} updated successfully!")
            return redirect(url_for("estimate_list"))
        
        # Create new
        ship_count = cdb.query(Estimate).filter_by(company_id=company_id).count()
        estimate_id = f"SHIP-{datetime.now().strftime('%Y%m%d')}-{ship_count + 1:03d}"
        
        est = Estimate(
            estimate_id=estimate_id,
            company_id=company_id,
            client_id=client_id,
            date=date.fromisoformat(request.form.get("invoice_date") or str(date.today())),
            status=status,
            contact_person=request.form.get("shipper_name", ""),
            email=request.form.get("notes", ""),
            phone=request.form.get("shipper_phone", ""),
            subtotal=subtotal,
            tax_amount=0,
            grand_total=grand_total,
            terms=terms_data,
        )
        cdb.add(est)
        cdb.flush()

        for item in line_items:
            cdb.add(EstimateItem(
                estimate_id=est.id,
                description=item["description"],
                hs_code=item.get("hs_code", ""),
                unit=item.get("unit", "Pc"),
                qty=item["qty"],
                rate=item["rate"],
                discount=0,
            ))
        
        cdb.commit()
        flash(f"Shipper Invoice {estimate_id} created successfully!")
        return redirect(url_for("estimate_list"))

    # Handle GET (Display form)
    # Get available dockets
    if existing:
        # For editing, exclude current estimate and add its docket to the list
        available_dockets = _get_available_dockets(company_id, exclude_estimate_id=existing.estimate_id)
    else:
        available_dockets = _get_available_dockets(company_id)

    if existing:
        # Parse stored data
        meta = {}
        try:
            meta = json.loads(existing.terms or "{}")
        except (ValueError, TypeError):
            meta = {}
        
        # Get line items from database
        line_items = []
        for item in existing.items:
            line_items.append({
                "description": item.description or "",
                "qty": item.qty or 0,
                "rate": item.rate or 0,
            })
        
        # If no items in DB, fall back to meta
        if not line_items and meta.get("line_items"):
            line_items = meta.get("line_items", [])
        
        # Add current docket to available_dockets if not already there
        current_docket_no = meta.get("docket_no", "")
        if current_docket_no:
            found = False
            for d in available_dockets:
                if d['docket_no'] == current_docket_no:
                    found = True
                    break
            if not found:
                available_dockets.insert(0, {
                    "invoice_id": meta.get("linked_invoice_id", ""),
                    "docket_no": current_docket_no,
                    "customer_name": "Current Selection",
                })
        
        form_data = {
            "estimate_id": existing.estimate_id,
            "invoice_date": existing.date.strftime("%Y-%m-%d") if existing.date else str(date.today()),
            "shipper_id": existing.client_id or "",
            "shipper_name": meta.get("shipper_name", existing.contact_person or ""),
            "shipper_phone": meta.get("shipper_phone", existing.phone or ""),
            "shipper_address": meta.get("shipper_address", ""),
            "receiver_name": meta.get("receiver_name", ""),
            "receiver_phone": meta.get("receiver_phone", ""),
            "receiver_company": meta.get("receiver_company", ""),
            "receiver_address": meta.get("receiver_address", ""),
            "destination": meta.get("destination", ""),
            "docket_no": current_docket_no,
            "linked_invoice_id": meta.get("linked_invoice_id", ""),
            "payment_mode": meta.get("payment_mode", "credit"),
            "upi_app": meta.get("upi_app", ""),
            "upi_ref": meta.get("upi_ref", ""),
            "cheque_no": meta.get("cheque_no", ""),
            "cheque_date": meta.get("cheque_date", ""),
            "cheque_bank": meta.get("cheque_bank", ""),
            "notes": existing.email or "",
            "weight": meta.get("weight", "0.00"),
            "reference": meta.get("reference", meta.get("aadhar", "")),
            "line_items": line_items,
        }
        
        
        return render_template(
            "estimate.html",
            clients=clients,
            estimate_id=existing.estimate_id,
            today=str(date.today()),
            form_data=form_data,
            available_dockets=available_dockets,
            edit_mode=True,
        )

    # New invoice
    ship_count = cdb.query(Estimate).filter_by(company_id=company_id).count()
    estimate_id = f"SHIP-{datetime.now().strftime('%Y%m%d')}-{ship_count + 1:03d}"

    return render_template(
        "estimate.html",
        clients=clients,
        estimate_id=estimate_id,
        today=str(date.today()),
        form_data={},
        available_dockets=available_dockets,
        edit_mode=False,
    )

@app.route("/estimate/edit/<estimate_id>")
@login_required
def estimate_edit(estimate_id):
    """Edit a Shipper Invoice"""
    return redirect(url_for("estimate_new", edit=estimate_id))

@app.route("/estimate/view/<estimate_id>")
@login_required
def estimate_view(estimate_id):
    cdb = get_cdb()
    company_id = get_current_company()
    est = _first_or_404(cdb.query(Estimate).filter_by(estimate_id=estimate_id, company_id=company_id).first())

    meta = {}
    if est.terms:
        try:
            meta = json.loads(est.terms)
        except (ValueError, TypeError):
            meta = {}

    items = []
    grand_total_calc = 0
    for li in est.items:
        qty      = float(li.qty or 0)
        rate     = float(li.rate or 0)
        discount = float(li.discount or 0)
        amount = qty * rate * (1 - discount / 100)
        grand_total_calc += amount
        items.append({
            "code":     li.code        or "",
            "desc":     li.description or "",
            "qty":      qty,
            "rate":     rate,
            "discount": discount,
            "amount":   amount,
        })

    # Use the calculated total if est.grand_total is 0 or None
    display_total = est.grand_total if est.grand_total else grand_total_calc

    estimate = {
        "id":            est.estimate_id,
        "date":          est.date.strftime("%d %b %Y") if est.date else "—",
        "valid_until":   est.valid_until.strftime("%d %b %Y") if est.valid_until else "—",
        "status":        est.status or "Draft",
        "grand_total":   display_total,
        "subtotal":      est.subtotal or grand_total_calc,
        "tax_amount":    est.tax_amount or 0,
        "client_name":   est.client_obj.name if est.client_obj else (est.contact_person or "—"),
        "contact_person":est.contact_person or "",
        "email":         est.email or "",
        "phone":         est.phone or "",
        "terms_text":    meta if not meta.get("docket_no") else "",
        "docket_no":         meta.get("docket_no", ""),
        "shipper_address":    meta.get("shipper_address", ""),
        "receiver_name":     meta.get("receiver_name", ""),
        "receiver_company":  meta.get("receiver_company", ""),
        "receiver_phone":    meta.get("receiver_phone", ""),
        "receiver_address":  meta.get("receiver_address", ""),
        "destination":       meta.get("destination", ""),
        "shipment_type":     meta.get("shipment_type", ""),
        "mode":              meta.get("mode", ""),
        "carrier":           meta.get("carrier", ""),
        "line_items":        items,
        "is_shipper":        bool(meta.get("docket_no") or est.estimate_id.startswith("SHIP-")),
        "weight":            meta.get("weight", "0.00"),
        "reference":         meta.get("aadhar", meta.get("reference", "")),
        "amount_words":      meta.get("amount_words", ""),
        "hs_codes":          meta.get("hs_codes", []),
        "dimensions": meta.get("dimensions", []),
    }

    return render_template("estimate_view.html", estimate=estimate)

@app.route("/estimate/save", methods=["POST"])
@login_required
def estimate_save():
    """Save a Shipper Invoice"""
    cdb = get_cdb()
    company_id = get_current_company()
    
    descriptions = request.form.getlist("description[]")
    qtys = request.form.getlist("qty[]")
    rates = request.form.getlist("rate[]")

    subtotal = 0
    line_items = []
    for i in range(len(descriptions)):
        if descriptions[i] and descriptions[i].strip():
            qty = float(qtys[i]) if qtys[i] else 0
            rate = float(rates[i]) if rates[i] else 0
            subtotal += qty * rate
            line_items.append({
                "description": descriptions[i],
                "qty": qty,
                "rate": rate,
            })

    grand_total = subtotal
    status = "Paid"

    client_id_raw = request.form.get("shipper_id")
    client_id = int(client_id_raw) if client_id_raw else None

    # Pack metadata into terms (including receiver_company and reference)
    terms_data = json.dumps({
        "docket_no": request.form.get("docket_no", ""),
        "linked_invoice_id": request.form.get("linked_invoice_id", ""),
        "shipper_name": request.form.get("shipper_name", ""),
        "shipper_phone": request.form.get("shipper_phone", ""),
        "shipper_address": request.form.get("shipper_address", ""),
        "receiver_name": request.form.get("receiver_name", ""),
        "receiver_phone": request.form.get("receiver_phone", ""),
        "receiver_company": request.form.get("receiver_company", ""),  # ADDED
        "receiver_address": request.form.get("receiver_address", ""),
        "destination": request.form.get("destination", ""),
        "weight": request.form.get("weight", "0.00"),
        "reference": request.form.get("reference", ""),  # ADDED (Aadhar/PAN)
        "line_items": line_items,
        "dimensions": [
    {
        "label": l,
        "l": lv, "w": wv, "h": hv, "wt": wt
    }
    for l, lv, wv, hv, wt in zip(
        request.form.getlist("dim_label[]"),
        request.form.getlist("dim_l[]"),
        request.form.getlist("dim_w[]"),
        request.form.getlist("dim_h[]"),
        request.form.getlist("dim_wt[]"),
    )
    if l
],
    })

    edit_invoice_id = request.form.get("edit_invoice_id", "").strip()
    existing = cdb.query(Estimate).filter_by(estimate_id=edit_invoice_id, company_id=company_id).first() if edit_invoice_id else None

    if existing:
        # Update existing
        existing.client_id = client_id
        existing.date = date.fromisoformat(request.form.get("invoice_date") or str(date.today()))
        existing.status = status
        existing.contact_person = request.form.get("shipper_name", "")
        existing.email = request.form.get("notes", "")
        existing.phone = request.form.get("shipper_phone", "")
        existing.subtotal = subtotal
        existing.tax_amount = 0
        existing.grand_total = grand_total
        existing.terms = terms_data

        # Replace items
        cdb.query(EstimateItem).filter_by(estimate_id=existing.id).delete()
        for item in line_items:
            cdb.add(EstimateItem(
                estimate_id=existing.id,
                description=item["description"],
                qty=item["qty"],
                rate=item["rate"],
                discount=0,
            ))
        
        cdb.commit()
        flash(f"Shipper Invoice {existing.estimate_id} updated successfully!")
        return redirect(url_for("estimate_list"))
    
    # Create new
    ship_count = cdb.query(Estimate).filter_by(company_id=company_id).count()
    estimate_id = f"SHIP-{datetime.now().strftime('%Y%m%d')}-{ship_count + 1:03d}"
    
    est = Estimate(
        estimate_id=estimate_id,
        company_id=company_id,
        client_id=client_id,
        date=date.fromisoformat(request.form.get("invoice_date") or str(date.today())),
        status=status,
        contact_person=request.form.get("shipper_name", ""),
        email=request.form.get("notes", ""),
        phone=request.form.get("shipper_phone", ""),
        subtotal=subtotal,
        tax_amount=0,
        grand_total=grand_total,
        terms=terms_data,
    )
    cdb.add(est)
    cdb.flush()

    for item in line_items:
        cdb.add(EstimateItem(
            estimate_id=est.id,
            description=item["description"],
            qty=item["qty"],
            rate=item["rate"],
            discount=0,
        ))
    
    cdb.commit()
    flash(f"Shipper Invoice {estimate_id} created successfully!")
    return redirect(url_for("estimate_list"))

# ── Manifest List ─────────────────────────────────────────────────────────────
@app.route('/manifest/list')
@login_required
def manifest_list():
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('login'))
    cdb = get_customer_session(company_id)

    from_date  = request.args.get('from_date')
    to_date    = request.args.get('to_date')
    shipper_id = request.args.get('shipper_id')
    courier    = request.args.get('courier', '').strip()

    q = cdb.query(CompanyManifest).filter_by(company_id=company_id)

    if from_date:
        try:
            q = q.filter(CompanyManifest.date >= date.fromisoformat(from_date))
        except ValueError:
            pass
    if to_date:
        try:
            q = q.filter(CompanyManifest.date <= date.fromisoformat(to_date))
        except ValueError:
            pass
    if shipper_id:
        q = q.filter(CompanyManifest.shipper_client_id == int(shipper_id))
    if courier:
        # filter manifests that have at least one entry matching the courier name
        q = q.join(ManifestEntry).filter(
            ManifestEntry.courier_name.ilike(f'%{courier}%')
        )

    manifests = q.order_by(CompanyManifest.date.desc(), CompanyManifest.id.desc()).all()

    clients      = cdb.query(Client).filter_by(company_id=company_id, status='Active').order_by(Client.name).all()
    total_boxes  = sum(m.total_boxes for m in manifests)
    courier_set  = set()
    for m in manifests:
        for e in m.entries:
            courier_set.add(e.courier_name.strip().lower())
    unique_couriers = len(courier_set)

    from collections import defaultdict
    grouped_manifests = defaultdict(list)
    for m in manifests:
        grouped_manifests[str(m.date)].append(m)
    date_keys = list(grouped_manifests.keys())

    return render_template(
        'manifest_list.html',
        manifests=manifests,
        clients=clients,
        from_date=from_date,
        to_date=to_date,
        shipper_id=shipper_id,
        courier=courier,
        total_manifests=len(manifests),
        total_boxes=total_boxes,
        unique_couriers=unique_couriers,
        grouped_manifests=grouped_manifests,
        date_keys=date_keys,
    )


# ── Manifest Create Form ───────────────────────────────────────────────────────
@app.route('/manifest/create')
@login_required
def manifest_create():
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('login'))
    cdb = get_customer_session(company_id)

    clients     = cdb.query(Client).filter_by(company_id=company_id, status='Active').order_by(Client.name).all()
    stock_items = cdb.query(StockItem).filter_by(company_id=company_id).order_by(StockItem.name).all()

    # Generate next manifest ID
    last = cdb.query(CompanyManifest).filter_by(company_id=company_id)\
               .order_by(CompanyManifest.id.desc()).first()
    next_num   = (last.id + 1) if last else 1
    manifest_id = f"MFT-{next_num:04d}"

    return render_template(
        'manifest_form.html',
        edit_mode=False,
        manifest_id=manifest_id,
        clients=clients,
        stock_items=stock_items,
        today=date.today().isoformat(),
    )

@app.route('/manifest/shipper-dockets/<int:client_id>')
@login_required
def shipper_last_dockets(client_id):
    company_id = get_current_company()
    if not company_id:
        return jsonify([])
    cdb = get_customer_session(company_id)

    invoices = (
        cdb.query(Invoice)
        .filter_by(company_id=company_id, client_id=client_id)
        .filter(Invoice.invoice_id.like('CUST-%'))
        .order_by(Invoice.id.desc())
        .all()
    )

    result = []
    seen = set()

    for inv in invoices:
        try:
            meta = json.loads(inv.terms) if inv.terms else {}
        except Exception:
            meta = {}

        docket = meta.get('docket_no', '').strip()
        if not docket or docket in seen:
            continue
        seen.add(docket)

        stock_items = []

        # ── Path 1: invoice_items has stock_item_id linked (ideal) ──
        linked_items = [line for line in inv.items if line.stock_item_id]
        if linked_items:
            for line in linked_items:
                stock = cdb.query(StockItem).filter_by(id=line.stock_item_id).first()
                if not stock:
                    continue
                already_used = (
                    cdb.query(func.sum(ManifestEntry.boxes))
                    .join(CompanyManifest, ManifestEntry.manifest_id == CompanyManifest.id)
                    .filter(
                        CompanyManifest.company_id == company_id,
                        ManifestEntry.docket_no == docket,
                        ManifestEntry.stock_item_id == stock.id
                    )
                    .scalar() or 0
                )
                available = max(0, int(line.qty) - int(already_used))
                stock_items.append({
                    'id':       stock.id,
                    'name':     stock.name,
                    'code':     stock.code or '',
                    'quantity': available,
                    'unit':     stock.unit or 'pcs'
                })

        # ── Path 2: no invoice_items — read packages from terms JSON ──
        else:
            packages = meta.get('packages', [])
            for pkg in packages:
                # packages may use 'name', 'type', or both
                pkg_name = (pkg.get('name') or pkg.get('type') or '').strip()
                pkg_qty  = float(pkg.get('qty') or 1)
                if not pkg_name:
                    continue

                # Match stock by exact name first, then partial
                stock = (
                    cdb.query(StockItem)
                    .filter(StockItem.company_id == company_id,
                            StockItem.name == pkg_name)
                    .first()
                ) or (
                    cdb.query(StockItem)
                    .filter(StockItem.company_id == company_id,
                            StockItem.name.ilike(f'%{pkg_name}%'))
                    .first()
                )

                if not stock:
                    continue

                # Avoid duplicates — sum qty if same stock appears twice
                existing = next((s for s in stock_items if s['id'] == stock.id), None)
                if existing:
                    existing['quantity'] += pkg_qty
                    continue

                already_used = (
                    cdb.query(func.sum(ManifestEntry.boxes))
                    .join(CompanyManifest, ManifestEntry.manifest_id == CompanyManifest.id)
                    .filter(
                        CompanyManifest.company_id == company_id,
                        ManifestEntry.docket_no == docket,
                        ManifestEntry.stock_item_id == stock.id
                    )
                    .scalar() or 0
                )
                available = max(0, int(pkg_qty) - int(already_used))
                stock_items.append({
                    'id':       stock.id,
                    'name':     stock.name,
                    'code':     stock.code or '',
                    'quantity': available,
                    'unit':     stock.unit or 'pcs'
                })

        result.append({
            'docket_id':   inv.id,
            'docket_no':   docket,
            'invoice_id':  inv.invoice_id,
            'date':        inv.date.strftime('%d %b %Y') if inv.date else '',
            'stock_items': stock_items
        })

    return jsonify(result)
    
@app.route('/manifest/invoice-packages/<int:client_id>/<docket_no>')
@login_required
def invoice_packages(client_id, docket_no):
    company_id = get_current_company()
    if not company_id:
        return jsonify({})
    cdb = get_customer_session(company_id)

    invoices = (
        cdb.query(Invoice)
        .filter_by(company_id=company_id, client_id=client_id)
        .all()
    )
    for inv in invoices:
        try:
            meta = json.loads(inv.terms) if inv.terms else {}
        except Exception:
            meta = {}
        if meta.get('docket_no', '').strip() == docket_no.strip():
            packages = meta.get('packages', [])
            # Aggregate by type
            summary = {}
            for p in packages:
                t = (p.get('type') or p.get('name') or 'Box').strip()
                q = float(p.get('qty') or 1)
                summary[t] = summary.get(t, 0) + q
            return jsonify({
                'invoice_id': inv.invoice_id,
                'date': inv.date.strftime('%d %b %Y') if inv.date else '',
                'packages': [{'type': k, 'qty': int(v)} for k, v in summary.items()]
            })
    return jsonify({'packages': []})

# ── Expenses ──────────────────────────────────────────────────────────────────
EXPENSE_CATEGORIES = [
    "Rent", "Electricity", "Internet", "Salaries", "Fuel",
    "Office Supplies", "Maintenance", "Travel", "Food & Refreshments",
    "Marketing", "Courier Charges", "Bank Charges", "Misc",
]

@app.route("/expenses")
@login_required
def expenses():
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('login'))
    cdb = get_customer_session(company_id)

    from_date = request.args.get("from_date", date.today().replace(day=1).isoformat())
    to_date   = request.args.get("to_date",   date.today().isoformat())

    try:
        fd = date.fromisoformat(from_date)
        td = date.fromisoformat(to_date)
    except ValueError:
        fd = date.today().replace(day=1)
        td = date.today()

    rows = (
        cdb.query(Expense)
        .filter(
            Expense.company_id == company_id,
            Expense.date >= fd,
            Expense.date <= td,
        )
        .order_by(Expense.date.desc(), Expense.id.desc())
        .all()
    )

    total = sum(e.amount for e in rows)

    # Category breakdown for chart
    cat_totals = {}
    for e in rows:
        cat_totals[e.category] = cat_totals.get(e.category, 0) + e.amount

    return render_template(
        "expenses.html",
        expenses=rows,
        total=total,
        cat_totals=cat_totals,
        categories=EXPENSE_CATEGORIES,
        from_date=from_date,
        to_date=to_date,
        today=date.today().isoformat(),
        today_str=date.today().isoformat(),
        active="expenses",
    )


@app.route("/expenses/add", methods=["GET", "POST"])
@login_required
def add_expense():
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('login'))
    cdb = get_customer_session(company_id)
    user       = get_current_user()

    if request.method == "POST":
        cdb = get_customer_session(company_id)
        try:
            exp = Expense(
                company_id   = company_id,
                date         = date.fromisoformat(request.form.get("date", date.today().isoformat())),
                category     = request.form.get("category", "Misc"),
                description  = request.form.get("description", "").strip(),
                amount       = float(request.form.get("amount", 0)),
                payment_mode = request.form.get("payment_mode", "Cash"),
                reference    = request.form.get("reference", "").strip(),
                created_by   = user.get("full_name", user.get("email")),
            )
            cdb.add(exp)
            cdb.commit()
            flash("Expense recorded successfully.", "success")
        except Exception as e:
            cdb.rollback()
            flash(f"Error: {str(e)}", "error")

        return redirect(url_for("expenses"))

    return redirect(url_for("expenses"))

@app.route("/expenses/delete/<int:expense_id>", methods=["POST"])
@login_required
def delete_expense(expense_id):
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('login'))
    cdb = get_customer_session(company_id)
    exp = cdb.query(Expense).filter_by(id=expense_id, company_id=company_id).first()
    if exp:
        cdb.delete(exp)
        cdb.commit()
        flash("Expense deleted.", "success")
    else:
        flash("Expense not found.", "error")
    return redirect(url_for("expenses"))


@app.route("/api/expenses-summary")
@login_required
def api_expenses_summary():
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('login'))
    cdb = get_customer_session(company_id)

    from_date = request.args.get("from_date", date.today().replace(day=1).isoformat())
    to_date   = request.args.get("to_date",   date.today().isoformat())

    try:
        fd = date.fromisoformat(from_date)
        td = date.fromisoformat(to_date)
    except ValueError:
        fd = date.today().replace(day=1)
        td = date.today()

    rows = cdb.query(Expense).filter(
        Expense.company_id == company_id,
        Expense.date >= fd,
        Expense.date <= td,
    ).all()

    cat_totals = {}
    for e in rows:
        cat_totals[e.category] = cat_totals.get(e.category, 0) + e.amount

    return jsonify({
        "total": sum(e.amount for e in rows),
        "count": len(rows),
        "by_category": cat_totals,
    })


# ── Manifest Save (POST) ───────────────────────────────────────────────────────
@app.route('/manifest/save', methods=['POST'])
@login_required
def manifest_save():
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('login'))
    cdb = get_customer_session(company_id)

    manifest_id       = request.form.get('manifest_id', '').strip()
    manifest_date_s   = request.form.get('manifest_date')
    shipper_client_id = int(request.form.get('shipper_client_id', 0))
    notes             = request.form.get('notes', '').strip()

    courier_names   = request.form.getlist('courier_name[]')
    boxes_list      = request.form.getlist('boxes[]')
    docket_nos      = request.form.getlist('docket_no[]')
    docket_ids      = request.form.getlist('docket_id[]')
    stock_item_ids  = request.form.getlist('stock_item_id[]')
    entry_notes     = request.form.getlist('entry_notes[]')

    # Build valid entries
    entries_data = []
    total_boxes = 0
    for i, cn in enumerate(courier_names):
        cn = cn.strip()
        bx = int(boxes_list[i]) if i < len(boxes_list) and boxes_list[i] else 0
        if cn and bx > 0:
            sid_raw = stock_item_ids[i] if i < len(stock_item_ids) else ''
            entries_data.append({
                'courier_name':   cn,
                'boxes':          bx,
                'docket_no':      docket_nos[i].strip() if i < len(docket_nos) else '',
                'docket_id':      int(docket_ids[i]) if i < len(docket_ids) and docket_ids[i] else None,
                'stock_item_id':  int(sid_raw) if sid_raw else None,
                'notes':          entry_notes[i].strip() if i < len(entry_notes) else '',
            })
            total_boxes += bx

    if not entries_data:
        flash('Add at least one courier row with boxes > 0.', 'danger')
        return redirect(url_for('manifest_create'))

    # Get shipper name
    shipper = cdb.query(Client).filter_by(id=shipper_client_id, company_id=company_id).first()
    if not shipper:
        flash('Shipper not found.', 'danger')
        return redirect(url_for('manifest_create'))

    try:
        manifest_date = date.fromisoformat(manifest_date_s)
    except (ValueError, TypeError):
        manifest_date = date.today()

    # Create manifest header
    manifest = CompanyManifest(
        manifest_id=manifest_id,
        company_id=company_id,
        date=manifest_date,
        shipper_client_id=shipper_client_id,
        shipper_client_name=shipper.name,
        total_boxes=total_boxes,
        notes=notes or None,
        created_by=session.get('user', {}).get('email', ''),
    )
    cdb.add(manifest)
    cdb.flush()  # get manifest.id

    # Deduct stock per entry and create entry rows
    stock_deductions = {}  # stock_item_id → total boxes to deduct
    for ed in entries_data:
        # Resolve stock name
        stock_name = None
        if ed['stock_item_id']:
            stock = cdb.query(StockItem).filter_by(id=ed['stock_item_id']).first()
            if stock:
                stock_name = stock.name
                stock_type = stock.item_type or stock.category or 'Box'
                stock_deductions[stock.id] = stock_deductions.get(stock.id, 0) + ed['boxes']

        entry = ManifestEntry(
            manifest_id=manifest.id,
            courier_name=ed['courier_name'],
            boxes=ed['boxes'],
            docket_no=ed['docket_no'] or None,
            docket_id=ed['docket_id'],
            stock_item_id=ed['stock_item_id'],
            stock_item_name=stock_name,
            notes=ed['notes'] or None,
            item_type=stock_type if ed['stock_item_id'] else 'Box',
        )
        cdb.add(entry)

    # Apply stock deductions
    for sid, qty in stock_deductions.items():
        stock = cdb.query(StockItem).filter_by(id=sid, company_id=company_id).first()
        if stock:
            stock.quantity -= qty
            stock.last_updated = date.today()

    cdb.commit()
    flash(f'Manifest {manifest_id} saved. {total_boxes} boxes deducted from stock.', 'success')
    return redirect(url_for('manifest_list'))


# ── Manifest View ──────────────────────────────────────────────────────────────
@app.route('/manifest/view/<int:manifest_db_id>')
@login_required
def manifest_view(manifest_db_id):
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('login'))
    cdb = get_customer_session(company_id)

    manifest = cdb.query(CompanyManifest).filter_by(
        id=manifest_db_id, company_id=company_id
    ).first()
    if not manifest:
        flash('Manifest not found.', 'danger')
        return redirect(url_for('manifest_list'))

    return render_template('manifest_view.html', manifest=manifest)


# ── Manifest Edit Form ─────────────────────────────────────────────────────────
@app.route('/manifest/edit/<int:manifest_db_id>')
@login_required
def manifest_edit(manifest_db_id):
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('login'))
    cdb = get_customer_session(company_id)

    manifest = cdb.query(CompanyManifest).filter_by(
        id=manifest_db_id, company_id=company_id
    ).first()
    if not manifest:
        flash('Manifest not found.', 'danger')
        return redirect(url_for('manifest_list'))

    clients     = cdb.query(Client).filter_by(company_id=company_id, status='Active').order_by(Client.name).all()
    stock_items = cdb.query(StockItem).filter_by(company_id=company_id).order_by(StockItem.name).all()

    return render_template(
        'manifest_form.html',
        edit_mode=True,
        manifest=manifest,
        manifest_id=manifest.manifest_id,
        clients=clients,
        stock_items=stock_items,
        today=date.today().isoformat(),
    )


# ── Manifest Update (POST) ─────────────────────────────────────────────────────
@app.route('/manifest/update/<int:manifest_db_id>', methods=['POST'])
@login_required
def manifest_update(manifest_db_id):
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('login'))
    cdb = get_customer_session(company_id)

    manifest = cdb.query(CompanyManifest).filter_by(
        id=manifest_db_id, company_id=company_id
    ).first()
    if not manifest:
        flash('Manifest not found.', 'danger')
        return redirect(url_for('manifest_list'))

    manifest_date_s  = request.form.get('manifest_date')
    new_stock_item_id= int(request.form.get('stock_item_id', 0))
    notes            = request.form.get('notes', '').strip()

    courier_names = request.form.getlist('courier_name[]')
    boxes_list    = request.form.getlist('boxes[]')
    docket_nos    = request.form.getlist('docket_no[]')
    entry_notes   = request.form.getlist('entry_notes[]')

    entries_data = []
    new_total = 0
    for i, cn in enumerate(courier_names):
        cn = cn.strip()
        bx = int(boxes_list[i]) if i < len(boxes_list) else 0
        if cn and bx > 0:
            entries_data.append({
                'courier_name': cn,
                'boxes': bx,
                'docket_no': docket_nos[i].strip() if i < len(docket_nos) else '',
                'notes': entry_notes[i].strip() if i < len(entry_notes) else '',
            })
            new_total += bx

    old_total    = manifest.total_boxes
    old_stock_id = manifest.stock_item_id
    diff         = new_total - old_total  # positive = need more stock

    # RIGHT - restore per original entry
    for entry in manifest.entries:
        if entry.stock_item_id:
            s = cdb.query(StockItem).filter_by(id=entry.stock_item_id, company_id=company_id).first()
            if s:
                s.quantity += entry.boxes
                s.last_updated = date.today()

    # Deduct from new stock item
    new_stock = cdb.query(StockItem).filter_by(id=new_stock_item_id, company_id=company_id).first()
    if not new_stock or new_stock.quantity < new_total:
        # Rollback the restore
        if old_stock:
            old_stock.quantity -= old_total
        flash(f'Not enough stock. Available: {new_stock.quantity if new_stock else 0}, Requested: {new_total}', 'danger')
        return redirect(url_for('manifest_edit', manifest_db_id=manifest_db_id))

    new_stock.quantity -= new_total
    new_stock.last_updated = date.today()
    if old_stock and old_stock.id != new_stock.id:
        old_stock.last_updated = date.today()

    # Update manifest header
    try:
        manifest.date = date.fromisoformat(manifest_date_s)
    except (ValueError, TypeError):
        pass
    manifest.stock_item_id = new_stock_item_id
    manifest.total_boxes   = new_total
    manifest.notes         = notes or None

    # Replace entries
    for e in list(manifest.entries):
        cdb.delete(e)
    for ed in entries_data:
        entry = ManifestEntry(
            manifest_id=manifest.id,
            courier_name=ed['courier_name'],
            boxes=ed['boxes'],
            docket_no=ed['docket_no'] or None,
            notes=ed['notes'] or None,
        )
        cdb.add(entry)

    cdb.commit()
    flash(f'Manifest updated. Stock adjusted accordingly.', 'success')
    return redirect(url_for('manifest_list'))


# ── Manifest Delete ────────────────────────────────────────────────────────────
@app.route('/manifest/delete/<int:manifest_db_id>')
@login_required
def manifest_delete(manifest_db_id):
    company_id = get_current_company()
    if not company_id:
        return redirect(url_for('login'))
    cdb = get_customer_session(company_id)

    manifest = cdb.query(CompanyManifest).filter_by(
        id=manifest_db_id, company_id=company_id
    ).first()
    if not manifest:
        flash('Manifest not found.', 'danger')
        return redirect(url_for('manifest_list'))

    # Restore stock on delete
    if manifest.stock_item_id:
        stock = cdb.query(StockItem).filter_by(id=manifest.stock_item_id, company_id=company_id).first()
        if stock:
            stock.quantity += manifest.total_boxes
            stock.last_updated = date.today()

    cdb.delete(manifest)
    cdb.commit()
    flash(f'Manifest {manifest.manifest_id} deleted. {manifest.total_boxes} boxes restored to stock.', 'success')
    return redirect(url_for('manifest_list'))

# ─────────────────────────────────────────────────────────────────────────────
# ── Super Admin ───────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
"""@app.route("/admin/dashboard")
@login_required
@super_admin_required
def admin_dashboard():
    cdb = get_cdb()
    stats = {
        "total_companies":  Company.query.count(),
        "total_users":      cdb.query(CompanyUser).count(),
        "active_companies": Company.query.filter_by(is_active=True).count(),
        "monthly_revenue":  0,
    }
    plan_distribution = {}
    for c in Company.query.all():
        plan_distribution[c.subscription_plan] = plan_distribution.get(c.subscription_plan, 0) + 1

    return render_template("super_admin.html",
                           stats=stats,
                           companies=Company.query.all(),
                           plans=get_all_plans(),
                           plan_distribution=plan_distribution)"""

@app.route("/migrations")
@login_required
@super_admin_required
def migrations():
    """Migration panel — list all past migrations across all company DBs."""
    from platform_models import Company
    from db_router import _engine_cache, _get_or_create

    companies = Company.query.filter_by(is_active=True).all()
    history   = []   # list of dicts for the template

    for company in companies:
        try:
            engine = _engine_cache.get(company.company_id)
            if engine is None:
                _get_or_create(company.company_id)
                engine = _engine_cache[company.company_id]

            _ensure_migration_table(engine)

            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT label, status, error_msg, applied_at, applied_by FROM schema_migrations ORDER BY applied_at DESC LIMIT 50")
                ).fetchall()

            for row in rows:
                history.append({
                    "company_id":   company.company_id,
                    "company_name": company.company_name,
                    "label":        row[0],
                    "status":       row[1],
                    "error_msg":    row[2],
                    "applied_at":   row[3],
                    "applied_by":   row[4],
                })
        except Exception as e:
            history.append({
                "company_id":   company.company_id,
                "company_name": company.company_name,
                "label":        "— could not read history —",
                "status":       "error",
                "error_msg":    str(e),
                "applied_at":   None,
                "applied_by":   None,
            })

    # Sort all history by applied_at desc
    history.sort(key=lambda x: x["applied_at"] or datetime.min, reverse=True)

    return render_template(
        "migrations.html",
        active="migrations",
        companies=companies,
        history=history,
    )


    return jsonify({"results": results, "summary": summary})

@app.route("/migrations/run", methods=["POST"])
@login_required
@super_admin_required
def run_migration():
    """
    Execute SQL on customer databases only.
    Platform database changes must be done manually.
    """
    from platform_models import Company
    from db_router import _engine_cache, _get_or_create

    data = request.get_json()
    label = (data.get("label") or "").strip()
    sql = (data.get("sql") or "").strip()
    target = data.get("target", "all")
    dry_run = data.get("dry_run", False)
    user_email = get_current_user().get("email", "unknown")

    if not label:
        return jsonify({"error": "Migration label is required"}), 400
    if not sql:
        return jsonify({"error": "SQL is required"}), 400

    # Determine which companies to target
    if target == "all":
        companies = Company.query.filter_by(is_active=True).all()
    else:
        companies = Company.query.filter_by(company_id=target, is_active=True).all()

    results = []

    for company in companies:
        company_id = company.company_id
        result = {
            "company_id": company_id,
            "company_name": company.company_name,
            "status": None,
            "message": "",
            "skipped": False,
        }

        try:
            engine = _engine_cache.get(company_id)
            if engine is None:
                _get_or_create(company_id)
                engine = _engine_cache[company_id]

            _ensure_migration_table(engine)

            # Skip if already applied successfully
            if _already_applied(engine, label):
                result["status"] = "skipped"
                result["message"] = "Already applied — skipped"
                result["skipped"] = True
                results.append(result)
                continue

            if dry_run:
                result["status"] = "dry_run"
                result["message"] = "Dry run — SQL not executed"
                results.append(result)
                continue

            # Run the SQL
            with engine.connect() as conn:
                statements = [s.strip() for s in sql.split(";") if s.strip()]
                for stmt in statements:
                    conn.execute(text(stmt))
                conn.commit()

            _log_migration(engine, label, sql, "success", None, user_email)
            result["status"] = "success"
            result["message"] = "Applied successfully"

        except Exception as e:
            err = str(e)
            try:
                _log_migration(engine, label, sql, "failed", err, user_email)
            except Exception:
                pass
            result["status"] = "failed"
            result["message"] = err

        results.append(result)

    summary = {
        "total": len(results),
        "success": sum(1 for r in results if r["status"] == "success"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "dry_run": sum(1 for r in results if r["status"] == "dry_run"),
    }

    return jsonify({"results": results, "summary": summary})


def _ensure_migration_table(engine):
    """Create migration history table in customer database if it doesn't exist"""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                label VARCHAR(200) NOT NULL,
                sql_executed TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                error_msg TEXT,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                applied_by VARCHAR(100)
            )
        """))
        conn.commit()


def _already_applied(engine, label):
    """Check if migration already applied to this customer DB"""
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE label = :label AND status = 'success'"),
            {"label": label}
        ).scalar()
        return result > 0


def _log_migration(engine, label, sql, status, error_msg, applied_by):
    """Log migration to customer database history table"""
    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO schema_migrations (label, sql_executed, status, error_msg, applied_by)
                VALUES (:label, :sql, :status, :error_msg, :applied_by)
            """),
            {
                "label": label,
                "sql": sql,
                "status": status,
                "error_msg": error_msg,
                "applied_by": applied_by
            }
        )
        conn.commit()

@app.route("/migrations/history")
@login_required
@super_admin_required
def migration_history_all():
    """
    Return combined migration history across ALL active companies as JSON.
    Called by the super_admin page when the Migrations tab is opened.
    """
    from platform_models import Company
    from db_router import _engine_cache, _get_or_create

    companies = Company.query.filter_by(is_active=True).all()
    all_rows  = []

    for company in companies:
        company_id = company.company_id
        try:
            engine = _engine_cache.get(company_id)
            if engine is None:
                _get_or_create(company_id)
                engine = _engine_cache[company_id]

            _ensure_migration_table(engine)

            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT label, sql_executed, status, error_msg, applied_at, applied_by FROM schema_migrations ORDER BY applied_at DESC LIMIT 100")
                ).fetchall()

            for r in rows:
                all_rows.append({
                    "company_id":   company_id,
                    "company_name": company.company_name,
                    "label":        r[0],
                    "sql":          r[1],
                    "status":       r[2],
                    "error_msg":    r[3],
                    "applied_at":   r[4].strftime("%d %b %Y %H:%M") if r[4] else "",
                    "applied_by":   r[5],
                    "_sort_key":    r[4].isoformat() if r[4] else "",
                })
        except Exception as e:
            pass  # Skip companies whose DB is unreachable

    # Sort newest first
    all_rows.sort(key=lambda x: x["_sort_key"], reverse=True)
    for row in all_rows:
        del row["_sort_key"]

    return jsonify({"history": all_rows})


@app.route("/migrations/history/<company_id>")
@login_required
@super_admin_required
def migration_history(company_id):
    """Return migration history for one specific company as JSON."""
    from db_router import _engine_cache, _get_or_create

    engine = _engine_cache.get(company_id)
    if engine is None:
        _get_or_create(company_id)
        engine = _engine_cache[company_id]

    _ensure_migration_table(engine)

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT label, sql_executed, status, error_msg, applied_at, applied_by FROM schema_migrations ORDER BY applied_at DESC")
        ).fetchall()

    history = [
        {
            "label":      r[0],
            "sql":        r[1],
            "status":     r[2],
            "error_msg":  r[3],
            "applied_at": r[4].strftime("%Y-%m-%d %H:%M:%S") if r[4] else "",
            "applied_by": r[5],
        }
        for r in rows
    ]

    return jsonify({"history": history})

@app.route("/admin/dashboard")
@login_required
@super_admin_required
def admin_dashboard():
    stats = {
        "total_companies":  Company.query.count(),
        "total_users":      0,  # Will calculate differently
        "active_companies": Company.query.filter_by(is_active=True).count(),
        "monthly_revenue":  0,
    }
    
    # Calculate total users across all companies
    companies = Company.query.all()
    for company in companies:
        try:
            cdb = get_customer_session(company.company_id, db_session=db.session)
            user_count = cdb.query(CompanyUser).count()
            stats["total_users"] += user_count
            from db_router import close_customer_session
            close_customer_session(company.company_id)
        except Exception:
            pass
    
    plan_distribution = {}
    for c in companies:
        plan_distribution[c.subscription_plan] = plan_distribution.get(c.subscription_plan, 0) + 1

    return render_template("super_admin.html",
                           stats=stats,
                           companies=companies,
                           plans=get_all_plans(),
                           plan_distribution=plan_distribution)


@app.route("/admin/companies")
@login_required
@super_admin_required
def admin_companies():
    return render_template("admin_companies.html", companies=Company.query.all())


@app.route("/admin/company/<company_id>")
@login_required
@super_admin_required
def admin_company_detail(company_id):
    cdb = get_cdb()
    company = get_company_by_id(company_id)
    users   = cdb.query(CompanyUser).filter_by(company_id=company_id).all()
    return render_template("admin_company_detail.html",
                           company=company, users=users, plans=get_all_plans())


@app.route("/admin/company/<company_id>/update-plan", methods=["POST"])
@login_required
@super_admin_required
def admin_update_company_plan(company_id):
    plan_id = request.form.get("plan")
    company = get_company_by_id(company_id)
    plan    = SubscriptionPlan.query.get(plan_id)
    if company and plan:
        company.subscription_plan     = plan.id
        company.max_companies_allowed = plan.max_companies
        company.max_users_per_company = plan.max_users
        cdb.commit()
        flash(f"Company plan updated to {plan.name}")
    return redirect(url_for("admin_company_detail", company_id=company_id))


@app.route("/admin/company/<company_id>/toggle-status", methods=["POST"])
@login_required
@super_admin_required
def admin_toggle_company_status(company_id):
    company = get_company_by_id(company_id)
    if company:
        company.is_active = not company.is_active
        cdb.commit()
        status = "activated" if company.is_active else "suspended"
        flash(f"Company {status}")
    return redirect(url_for("admin_company_detail", company_id=company_id))


# ─────────────────────────────────────────────────────────────────────────────
# ── Employee Management ───────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/employees")
@login_required
@owner_required
def employee_list():
    cdb = get_cdb()
    company_id = get_current_company()
    employees  = cdb.query(CompanyUser).filter_by(company_id=company_id).all()
    return render_template("employees.html", employees=employees)


@app.route("/employees/add", methods=["GET", "POST"])
@login_required
@owner_required
def employee_add():
    cdb = get_cdb()
    company_id = get_current_company()
    can_add, msg = check_company_limit(company_id, "user")
    if not can_add:
        flash(msg)
        return redirect(url_for("employee_list"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        emp_count = cdb.query(CompanyUser).count()
        emp_id    = f"EMP{emp_count + 1:03d}"
        new_emp   = CompanyUser(
            user_id=emp_id, company_id=company_id, email=email,
            password_hash=hash_password(password),
            full_name=request.form.get("full_name", ""),
            role=request.form.get("role", "employee"),
            department=request.form.get("department", ""),
            phone=request.form.get("phone", ""),
            is_active=True, created_at=date.today(),
        )
        cdb.add(new_emp)
        cdb.commit()
        flash("Employee added!")
        return redirect(url_for("employee_list"))
    return render_template("employee_form.html")


@app.route("/employees/toggle/<user_id>", methods=["POST"])
@login_required
@owner_required
def employee_toggle(user_id):
    cdb = get_cdb()
    company_id = get_current_company()
    emp        = _first_or_404(cdb.query(CompanyUser).filter_by(user_id=user_id, company_id=company_id).first())
    emp.is_active = not emp.is_active
    cdb.commit()
    flash(f"Employee {'activated' if emp.is_active else 'deactivated'}.")
    return redirect(url_for("employee_list"))


# ─────────────────────────────────────────────────────────────────────────────
# ── Product Lookup API ────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/product/<code>")
@login_required
def api_product_lookup(code):
    cdb = get_cdb()
    company_id = get_current_company()
    code_clean = code.strip().upper()
    item = cdb.query(StockItem).filter_by(company_id=company_id, code=code_clean).first()
    if not item:
        item = cdb.query(StockItem).filter(
            StockItem.company_id == company_id,
            StockItem.name.ilike(f"%{code_clean}%")
        ).first()
    if not item:
        return jsonify({"found": False, "message": f"No product found for '{code}'"}), 404
    return jsonify({
        "found": True, "code": item.code, "name": item.name,
        "rate": item.unit_price, "unit": item.unit or "pcs",
        "category": item.category or "", "stock": item.quantity,
        "hsn": item.hsn or "",
        "low_stock": item.quantity <= item.reorder_level,
    }), 200


@app.route("/api/products/search")
@login_required
def api_products_search():
    cdb = get_cdb()
    company_id = get_current_company()
    q = request.args.get("q", "").strip().upper()
    if not q:
        return jsonify({"results": []})
    items = cdb.query(StockItem).filter(
        StockItem.company_id == company_id,
        db.or_(StockItem.code.ilike(f"%{q}%"), StockItem.name.ilike(f"%{q}%"))
    ).limit(8).all()
    return jsonify({"results": [{
        "code": s.code, "name": s.name, "rate": s.unit_price,
        "unit": s.unit or "pcs", "stock": s.quantity, "hsn": s.hsn or "",
    } for s in items]})


# ============================================
# BANK ACCOUNTS & FINANCE ROUTES
# ============================================

# ============================================
# CASH IN HAND ROUTES
# ============================================

@app.route("/cash-in-hand")
@login_required
def cash_in_hand():
    """Cash in hand tracking"""
    cdb = get_cdb()
    company_id = get_current_company()
    
    # Get filter parameters
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    filter_type = request.args.get('type', 'all')
    
    # Set default dates (last 30 days)
    if not from_date_str:
        from_date = date.today() - timedelta(days=30)
    else:
        from_date = date.fromisoformat(from_date_str)
    
    if not to_date_str:
        to_date = date.today()
    else:
        to_date = date.fromisoformat(to_date_str)
    
    # Build query
    query = cdb.query(CashTransaction).filter(
        CashTransaction.company_id == company_id,
        CashTransaction.date >= from_date,
        CashTransaction.date <= to_date
    )
    
    if filter_type != 'all':
        query = query.filter(CashTransaction.type == filter_type)
    
    transactions = query.order_by(CashTransaction.date.desc()).all()
    
    # Calculate totals
    total_inflow = sum(t.amount for t in transactions if t.type == 'income')
    total_outflow = sum(t.amount for t in transactions if t.type == 'expense')
    
    # Calculate current balance (all time)
    all_income = cdb.query(CashTransaction).filter_by(company_id=company_id, type='income').all()
    all_expense = cdb.query(CashTransaction).filter_by(company_id=company_id, type='expense').all()
    current_balance = sum(t.amount for t in all_income) - sum(t.amount for t in all_expense)
    
    # Format transactions for template
    running_balance = 0
    all_transactions = cdb.query(CashTransaction).filter_by(company_id=company_id).order_by(CashTransaction.date.asc()).all()
    
    # Create a dict of running balances
    balance_map = {}
    for t in all_transactions:
        if t.type == 'income':
            running_balance += t.amount
        else:
            running_balance -= t.amount
        balance_map[t.id] = running_balance
    
    transactions_list = []
    for t in transactions:
        transactions_list.append({
            'id': t.id,
            'date': t.date.strftime('%d %b %Y'),
            'type': t.type,
            'category': t.category,
            'description': t.description,
            'amount': t.amount,
            'reference': t.reference or '',
            'notes': t.notes or '',
            'balance_after': balance_map.get(t.id, 0)
        })
    
    return render_template("cash_in_hand.html",
                         active='cash_in_hand',
                         current_balance=current_balance,
                         total_inflow=total_inflow,
                         total_outflow=total_outflow,
                         transactions=transactions_list,
                         from_date=from_date.strftime('%Y-%m-%d'),
                         to_date=to_date.strftime('%Y-%m-%d'),
                         today=date.today().strftime('%Y-%m-%d'))


@app.route("/api/cash-transaction/save", methods=["POST"])
@login_required
def save_cash_transaction():
    """Save a cash transaction"""
    company_id = get_current_company()
    data = request.get_json()
    
    try:
        transaction = CashTransaction(
            company_id=company_id,
            type=data.get('type'),
            date=date.fromisoformat(data.get('date')),
            category=data.get('category'),
            description=data.get('description'),
            amount=data.get('amount'),
            reference=data.get('reference', ''),
            notes=data.get('notes', ''),
            created_by=get_current_user().get('email')
        )
        cdb.add(transaction)
        cdb.commit()
        
        return jsonify({'success': True, 'message': 'Transaction saved successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


@app.route("/api/cash-transaction/delete/<int:txn_id>", methods=["DELETE"])
@login_required
def delete_cash_transaction(txn_id):
    """Delete a cash transaction"""
    cdb = get_cdb()
    company_id = get_current_company()
    transaction = cdb.query(CashTransaction).filter_by(id=txn_id, company_id=company_id).first()
    
    if not transaction:
        return jsonify({'success': False, 'message': 'Transaction not found'}), 404
    
    try:
        cdb.delete(transaction)
        cdb.commit()
        return jsonify({'success': True, 'message': 'Transaction deleted'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

# ============================================
# BANK ACCOUNTS ROUTES
# ============================================

@app.route("/bank-accounts")
@login_required
def bank_accounts():
    """Bank Accounts management page"""
    cdb = get_cdb()
    company_id = get_current_company()
    bank_accounts = cdb.query(BankAccount).filter_by(company_id=company_id, status='Active').all()
    
    # Calculate total balance
    total_balance = sum(acc.balance for acc in bank_accounts)
    
    return render_template("bank_accounts.html", 
                         active='bank_accounts',
                         bank_accounts=bank_accounts,
                         total_balance=total_balance)


@app.route("/bank-accounts/add", methods=["POST"])
@login_required
def add_bank_account():
    """Add a new bank account"""
    cdb = get_cdb()
    company_id = get_current_company()
    
    bank_name = request.form.get("bank_name", "").strip()
    account_name = request.form.get("account_name", "").strip()
    account_number = request.form.get("account_number", "").strip()
    ifsc_code = request.form.get("ifsc_code", "").strip()
    branch = request.form.get("branch", "").strip()
    opening_balance = float(request.form.get("balance", 0) or 0)
    
    if not bank_name or not account_name or not account_number:
        flash("Bank Name, Account Name, and Account Number are required!")
        return redirect(url_for("bank_accounts"))
    
    # Check if account number already exists for this company
    existing = cdb.query(BankAccount).filter_by(company_id=company_id, account_number=account_number).first()
    if existing:
        flash(f"Account number {account_number} already exists!")
        return redirect(url_for("bank_accounts"))
    
    new_account = BankAccount(
        company_id=company_id,
        bank_name=bank_name,
        account_name=account_name,
        account_number=account_number,
        ifsc_code=ifsc_code,
        branch=branch,
        opening_balance=opening_balance,
        balance=opening_balance,
        status='Active',
        created_at=datetime.utcnow()
    )
    
    cdb.add(new_account)
    
    # Add opening balance transaction if opening_balance > 0
    if opening_balance > 0:
        opening_txn = BankTransaction(
            bank_account_id=new_account.id,
            company_id=company_id,
            type='credit',
            date=date.today(),
            description=f"Opening Balance for {bank_name} - {account_name}",
            amount=opening_balance,
            reference="Opening Balance",
            transaction_mode="Cash",
            created_by=get_current_user().get('email')
        )
        cdb.add(opening_txn)
    
    cdb.commit()
    flash(f"Bank account {bank_name} - {account_name} added successfully!")
    return redirect(url_for("bank_accounts"))


@app.route("/bank-accounts/<int:account_id>/transactions")
@login_required
def bank_transactions(account_id):
    """View transactions for a specific bank account"""
    cdb = get_cdb()
    company_id = get_current_company()
    account = _first_or_404(cdb.query(BankAccount).filter_by(id=account_id, company_id=company_id).first())
    
    # Get filter parameters
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    txn_type = request.args.get('type', 'all')
    
    # Set default dates (last 30 days)
    if not from_date_str:
        from_date = date.today() - timedelta(days=30)
    else:
        from_date = date.fromisoformat(from_date_str)
    
    if not to_date_str:
        to_date = date.today()
    else:
        to_date = date.fromisoformat(to_date_str)
    
    # Build query
    query = cdb.query(BankTransaction).filter(
        BankTransaction.bank_account_id == account_id,
        BankTransaction.company_id == company_id,
        BankTransaction.date >= from_date,
        BankTransaction.date <= to_date
    )
    
    if txn_type != 'all':
        query = query.filter(BankTransaction.type == txn_type)
    
    transactions = query.order_by(BankTransaction.date.desc()).all()
    
    # Calculate totals
    total_credits = sum(t.amount for t in transactions if t.type == 'credit')
    total_debits = sum(t.amount for t in transactions if t.type == 'debit')
    
    return render_template("bank_transactions.html",
                         active='bank_accounts',
                         account=account,
                         transactions=transactions,
                         total_credits=total_credits,
                         total_debits=total_debits,
                         from_date=from_date.strftime('%Y-%m-%d'),
                         to_date=to_date.strftime('%Y-%m-%d'),
                         today=date.today().strftime('%Y-%m-%d'))


@app.route("/bank-accounts/<int:account_id>/add-transaction", methods=["POST"])
@login_required
def add_bank_transaction(account_id):
    """Add a transaction to a bank account"""
    cdb = get_cdb()
    company_id = get_current_company()
    account = _first_or_404(cdb.query(BankAccount).filter_by(id=account_id, company_id=company_id).first())
    
    txn_type = request.form.get("type")
    date_str = request.form.get("date")
    description = request.form.get("description", "").strip()
    amount = float(request.form.get("amount", 0))
    reference = request.form.get("reference", "").strip()
    transaction_mode = request.form.get("transaction_mode", "Transfer")
    notes = request.form.get("notes", "").strip()
    
    if not description or amount <= 0:
        flash("Description and valid amount are required!")
        return redirect(url_for("bank_transactions", account_id=account_id))
    
    # Create transaction
    transaction = BankTransaction(
        bank_account_id=account.id,
        company_id=company_id,
        type=txn_type,
        date=date.fromisoformat(date_str) if date_str else date.today(),
        description=description,
        amount=amount,
        reference=reference,
        transaction_mode=transaction_mode,
        notes=notes,
        created_by=get_current_user().get('email')
    )
    cdb.add(transaction)
    
    # Update account balance
    if txn_type == 'credit':
        account.balance += amount
    else:
        account.balance -= amount
    
    account.updated_at = datetime.utcnow()
    
    cdb.commit()
    flash(f"{'Deposit' if txn_type == 'credit' else 'Withdrawal'} of ₹{amount:,.2f} recorded successfully!")
    return redirect(url_for("bank_transactions", account_id=account_id))


@app.route("/bank-accounts/<int:account_id>/delete", methods=["GET", "POST"])
@login_required
def delete_bank_account(account_id):
    """Delete a bank account (soft delete by setting status to Inactive)"""
    cdb = get_cdb()
    company_id = get_current_company()
    account = _first_or_404(cdb.query(BankAccount).filter_by(id=account_id, company_id=company_id).first())
    
    # Soft delete - just mark as inactive
    account.status = 'Inactive'
    cdb.commit()
    
    flash(f"Bank account {account.bank_name} - {account.account_name} has been deactivated.")
    return redirect(url_for("bank_accounts"))


@app.route("/bank-accounts/<int:account_id>/transfer", methods=["POST"])
@login_required
def bank_transfer(account_id):
    """Transfer money between bank accounts"""
    cdb = get_cdb()
    company_id = get_current_company()
    from_account = _first_or_404(cdb.query(BankAccount).filter_by(id=account_id, company_id=company_id).first())
    
    to_account_id = request.form.get("to_account_id", type=int)
    amount = float(request.form.get("amount", 0))
    date_str = request.form.get("date")
    description = request.form.get("description", "").strip()
    reference = request.form.get("reference", "").strip()
    
    to_account = cdb.query(BankAccount).filter_by(id=to_account_id, company_id=company_id).first()
    
    if not to_account:
        flash("Destination account not found!")
        return redirect(url_for("bank_transactions", account_id=account_id))
    
    if amount <= 0:
        flash("Amount must be greater than 0!")
        return redirect(url_for("bank_transactions", account_id=account_id))
    
    if from_account.balance < amount:
        flash(f"Insufficient balance in {from_account.bank_name} - {from_account.account_name}!")
        return redirect(url_for("bank_transactions", account_id=account_id))
    
    txn_date = date.fromisoformat(date_str) if date_str else date.today()
    
    # Debit transaction from source account
    debit_txn = BankTransaction(
        bank_account_id=from_account.id,
        company_id=company_id,
        type='debit',
        date=txn_date,
        description=f"Transfer to {to_account.bank_name} - {to_account.account_name}: {description}" if description else f"Transfer to {to_account.bank_name} - {to_account.account_name}",
        amount=amount,
        reference=reference,
        transaction_mode="Transfer",
        notes=f"Transfer from {from_account.bank_name} to {to_account.bank_name}",
        created_by=get_current_user().get('email')
    )
    cdb.add(debit_txn)
    from_account.balance -= amount
    
    # Credit transaction to destination account
    credit_txn = BankTransaction(
        bank_account_id=to_account.id,
        company_id=company_id,
        type='credit',
        date=txn_date,
        description=f"Transfer from {from_account.bank_name} - {from_account.account_name}: {description}" if description else f"Transfer from {from_account.bank_name} - {from_account.account_name}",
        amount=amount,
        reference=reference,
        transaction_mode="Transfer",
        notes=f"Transfer from {from_account.bank_name} to {to_account.bank_name}",
        created_by=get_current_user().get('email')
    )
    cdb.add(credit_txn)
    to_account.balance += amount
    
    from_account.updated_at = datetime.utcnow()
    to_account.updated_at = datetime.utcnow()
    
    cdb.commit()
    flash(f"Transferred ₹{amount:,.2f} from {from_account.bank_name} to {to_account.bank_name} successfully!")
    return redirect(url_for("bank_transactions", account_id=account_id))

@app.route("/cheques")
@login_required
def cheques():
    """Cheque management"""
    company_id = get_current_company()
    return render_template("cheques.html", active='cheques')

# ============================================
# LOAN ACCOUNTS ROUTES
# ============================================

@app.route("/loan-accounts")
@login_required
def loan_accounts():
    """Loan accounts management"""
    cdb = get_cdb()
    company_id = get_current_company()
    
    # Get all loans
    all_loans = cdb.query(Loan).filter_by(company_id=company_id).all()
    
    # Separate by type
    loans_given = []
    loans_taken = []
    
    for loan in all_loans:
        payments = []
        for payment in loan.repayments:
            payments.append({
                'id': payment.id,
                'date': payment.date.strftime('%d %b %Y'),
                'amount': payment.amount,
                'payment_mode': payment.payment_mode,
                'reference': payment.reference or '',
                'notes': payment.notes or ''
            })
        
        loan_dict = {
            'id': loan.id,
            'type': loan.type,
            'party_name': loan.party_name,
            'loan_date': loan.loan_date.strftime('%d %b %Y'),
            'amount': loan.amount,
            'remaining_amount': loan.remaining_amount,
            'repaid_amount': loan.repaid_amount,
            'repayment_percentage': loan.repayment_percentage,
            'interest_rate': loan.interest_rate,
            'tenure': loan.tenure,
            'emi_amount': loan.emi_amount,
            'purpose': loan.purpose or '',
            'notes': loan.notes or '',
            'status': loan.status,
            'payments': payments
        }
        
        if loan.type == 'given':
            loans_given.append(loan_dict)
        else:
            loans_taken.append(loan_dict)
    
    # Calculate totals
    total_given = sum(l.amount for l in all_loans if l.type == 'given')
    total_taken = sum(l.amount for l in all_loans if l.type == 'taken')
    total_repaid = sum(l.repaid_amount for l in all_loans)
    
    return render_template("loan_accounts.html",
                         active='loan_accounts',
                         loans_given=loans_given,
                         loans_taken=loans_taken,
                         total_given=total_given,
                         total_taken=total_taken,
                         total_repaid=total_repaid,
                         today=date.today().strftime('%Y-%m-%d'))


@app.route("/api/loan/save", methods=["POST"])
@login_required
def save_loan():
    """Save a new loan"""
    company_id = get_current_company()
    data = request.get_json()
    
    try:
        loan = Loan(
            company_id=company_id,
            type=data.get('type'),
            party_name=data.get('party_name'),
            loan_date=date.fromisoformat(data.get('loan_date')),
            amount=data.get('amount'),
            interest_rate=data.get('interest_rate', 0),
            tenure=data.get('tenure', 12),
            emi_amount=data.get('emi_amount', 0),
            purpose=data.get('purpose', ''),
            notes=data.get('notes', ''),
            status='Active',
            created_by=get_current_user().get('email')
        )
        cdb.add(loan)
        cdb.commit()
        
        return jsonify({'success': True, 'message': 'Loan saved successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


@app.route("/api/loan/repayment/save", methods=["POST"])
@login_required
def save_loan_repayment():
    """Save a loan repayment"""
    cdb = get_cdb()
    company_id = get_current_company()
    data = request.get_json()
    
    try:
        loan_id = data.get('loan_id')
        loan = cdb.query(Loan).filter_by(id=loan_id, company_id=company_id).first()
        
        if not loan:
            return jsonify({'success': False, 'message': 'Loan not found'}), 404
        
        repayment = LoanRepayment(
            loan_id=loan.id,
            date=date.fromisoformat(data.get('date')),
            amount=data.get('amount'),
            payment_mode=data.get('payment_mode', 'Cash'),
            reference=data.get('reference', ''),
            notes=data.get('notes', '')
        )
        cdb.add(repayment)
        
        # Update loan status if fully repaid
        if loan.remaining_amount - repayment.amount <= 0:
            loan.status = 'Completed'
        
        cdb.commit()
        
        return jsonify({'success': True, 'message': 'Repayment recorded successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400

# ============================================
# LEDGER & TRIAL BALANCE ROUTES
# ============================================

@app.route("/ledger")
@login_required
def ledger():
    """General Ledger - shows all transactions with filters"""
    cdb = get_cdb()
    company_id = get_current_company()
    
    # Get filter parameters
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    account_type = request.args.get('account_type', 'all')
    
    # Set default dates (last 30 days)
    if not from_date_str:
        from_date = date.today() - timedelta(days=30)
    else:
        from_date = date.fromisoformat(from_date_str)
    
    if not to_date_str:
        to_date = date.today()
    else:
        to_date = date.fromisoformat(to_date_str)
    
    ledger_entries = []
    
    # 1. Sales Invoices
    invoices = cdb.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.date >= from_date,
        Invoice.date <= to_date
    ).order_by(Invoice.date.asc()).all()
    
    for inv in invoices:
        client_name = inv.client_obj.name if inv.client_obj else (inv.contact_person or "Unknown")
        
        # Skip if filtering by account type
        if account_type != 'all' and account_type != 'sales':
            pass
        else:
            ledger_entries.append({
                'date': inv.date,
                'voucher_type': 'Sales Invoice',
                'voucher_no': inv.invoice_id,
                'party_name': client_name,
                'debit': inv.grand_total or 0,
                'credit': 0,
                'balance': 0,  # Will calculate running balance
                'type': 'sales'
            })
            
            # Add payment entries if paid
            paid_amount = (inv.grand_total or 0) - (getattr(inv, 'balance', 0) or 0)
            if paid_amount > 0:
                ledger_entries.append({
                    'date': inv.date,
                    'voucher_type': 'Payment Received',
                    'voucher_no': inv.invoice_id,
                    'party_name': client_name,
                    'debit': 0,
                    'credit': paid_amount,
                    'balance': 0,
                    'type': 'payment_received'
                })
    
    # 2. Purchase Invoices
    purchases = cdb.query(PurchaseInvoice).filter(
        PurchaseInvoice.company_id == company_id,
        PurchaseInvoice.date >= from_date,
        PurchaseInvoice.date <= to_date
    ).order_by(PurchaseInvoice.date.asc()).all()
    
    for pur in purchases:
        supplier_name = pur.supplier.name if pur.supplier else "Unknown"
        
        if account_type != 'all' and account_type != 'purchases':
            pass
        else:
            ledger_entries.append({
                'date': pur.date,
                'voucher_type': 'Purchase Invoice',
                'voucher_no': pur.invoice_number or pur.invoice_id,
                'party_name': supplier_name,
                'debit': 0,
                'credit': pur.grand_total or 0,
                'balance': 0,
                'type': 'purchases'
            })
            
            # Add payment entries if paid
            if pur.paid_amount and pur.paid_amount > 0:
                ledger_entries.append({
                    'date': pur.date,
                    'voucher_type': 'Payment Made',
                    'voucher_no': pur.invoice_number or pur.invoice_id,
                    'party_name': supplier_name,
                    'debit': pur.paid_amount,
                    'credit': 0,
                    'balance': 0,
                    'type': 'payment_made'
                })
    
    # 3. Expenses (if any expense table exists - you can add later)
    # 4. Bank transactions (if any bank table exists - you can add later)
    
    # Sort by date
    ledger_entries.sort(key=lambda x: x['date'])
    
    # Calculate running balance
    running_balance = 0
    for entry in ledger_entries:
        running_balance = running_balance + entry['debit'] - entry['credit']
        entry['balance'] = running_balance
    
    # Calculate totals
    total_debits = sum(e['debit'] for e in ledger_entries)
    total_credits = sum(e['credit'] for e in ledger_entries)
    closing_balance = running_balance
    
    return render_template('ledger.html',
                         ledger_entries=ledger_entries,
                         from_date=from_date,
                         to_date=to_date,
                         account_type=account_type,
                         total_debits=total_debits,
                         total_credits=total_credits,
                         closing_balance=closing_balance,
                         active='ledger')


@app.route("/trial-balance")
@login_required
def trial_balance():
    """Trial Balance - shows all account balances"""
    cdb = get_cdb()
    company_id = get_current_company()
    
    # Get filter parameter
    as_on_date_str = request.args.get('as_on_date', '')
    
    if not as_on_date_str:
        as_on_date = date.today()
    else:
        as_on_date = date.fromisoformat(as_on_date_str)
    
    accounts = {}
    
    # 1. Sales/Customers (Debtors)
    clients = cdb.query(Client).filter_by(company_id=company_id).all()
    for client in clients:
        # Calculate outstanding from invoices
        invoices = cdb.query(Invoice).filter_by(company_id=company_id, client_id=client.id).all()
        total_sales = sum(i.grand_total or 0 for i in invoices)
        total_paid = sum((i.grand_total or 0) - (getattr(i, 'balance', 0) or 0) for i in invoices)
        outstanding = total_sales - total_paid
        
        if outstanding != 0:
            accounts[f"Debtors - {client.name}"] = {
                'debit': outstanding if outstanding > 0 else 0,
                'credit': abs(outstanding) if outstanding < 0 else 0
            }
    
    # 2. Suppliers (Creditors)
    suppliers = cdb.query(Client).filter(
        Client.company_id == company_id,
        db.or_(Client.client_type == "Supplier", Client.client_type == "Both")
    ).all()
    
    for supplier in suppliers:
        purchases = cdb.query(PurchaseInvoice).filter_by(company_id=company_id, supplier_id=supplier.id).all()
        total_purchases = sum(p.grand_total or 0 for p in purchases)
        total_paid = sum(p.paid_amount or 0 for p in purchases)
        outstanding = total_purchases - total_paid
        
        if outstanding != 0:
            accounts[f"Creditors - {supplier.name}"] = {
                'debit': 0,
                'credit': outstanding if outstanding > 0 else 0
            }
    
    # 3. Sales Revenue
    all_invoices = cdb.query(Invoice).filter_by(company_id=company_id).all()
    total_revenue = sum(i.grand_total or 0 for i in all_invoices)
    if total_revenue > 0:
        accounts["Sales Revenue"] = {
            'debit': 0,
            'credit': total_revenue
        }
    
    # 4. Purchase Cost
    all_purchases = cdb.query(PurchaseInvoice).filter_by(company_id=company_id).all()
    total_purchase_cost = sum(p.grand_total or 0 for p in all_purchases)
    if total_purchase_cost > 0:
        accounts["Purchase Cost"] = {
            'debit': total_purchase_cost,
            'credit': 0
        }
    
    # 5. Stock/Inventory Value
    stock_items = cdb.query(StockItem).filter_by(company_id=company_id).all()
    total_stock_value = sum((s.purchase_rate or s.unit_price or 0) * s.quantity for s in stock_items)
    if total_stock_value > 0:
        accounts["Inventory"] = {
            'debit': total_stock_value,
            'credit': 0
        }
    
    # 6. GST Collected (from sales)
    total_gst_collected = sum(i.tax_amount or 0 for i in all_invoices)
    if total_gst_collected > 0:
        accounts["GST Collected (Output)"] = {
            'debit': 0,
            'credit': total_gst_collected
        }
    
    # 7. GST Paid (on purchases)
    total_gst_paid = sum(p.tax_amount or 0 for p in all_purchases)
    if total_gst_paid > 0:
        accounts["GST Paid (Input)"] = {
            'debit': total_gst_paid,
            'credit': 0
        }
    
    # Calculate totals
    total_debits = sum(acc['debit'] for acc in accounts.values())
    total_credits = sum(acc['credit'] for acc in accounts.values())
    
    # Convert to list for template
    account_list = [{'name': name, 'debit': data['debit'], 'credit': data['credit']} 
                    for name, data in accounts.items()]
    
    # Sort by name
    account_list.sort(key=lambda x: x['name'])
    
    return render_template('trial_balance.html',
                         accounts=account_list,
                         total_debits=total_debits,
                         total_credits=total_credits,
                         as_on_date=as_on_date,
                         difference=total_debits - total_credits,
                         active='trial_balance')

# ============================================
# REPORTS ROUTES
# ============================================

@app.route("/api/reports/sales-data")
@login_required
def api_sales_report_data():
    """API endpoint for sales report data"""
    cdb = get_cdb()
    if not cdb:
        return jsonify({"error": "Could not connect to company database"}), 500
    
    company_id = get_current_company()
    
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    
    if not from_date_str:
        from_date = date.today().replace(day=1)
    else:
        from_date = date.fromisoformat(from_date_str)
    
    if not to_date_str:
        to_date = date.today()
    else:
        to_date = date.fromisoformat(to_date_str)
    
    # Get invoices (exclude draft)
    invoices = cdb.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.date >= from_date,
        Invoice.date <= to_date,
        Invoice.status.notin_(['Cancelled', 'Void'])
    ).order_by(Invoice.date.desc()).all()
    
    # Calculate totals
    total_revenue = sum(float(i.grand_total or 0) for i in invoices)
    total_tax = sum(float(i.tax_amount or 0) for i in invoices)
    total_pending = sum(float(getattr(i, 'balance', 0) or 0) for i in invoices)
    total_received = total_revenue - total_pending
    
    # Monthly trend
    monthly_revenue = {}
    for inv in invoices:
        month_key = inv.date.strftime('%b %Y')
        monthly_revenue[month_key] = monthly_revenue.get(month_key, 0) + float(inv.grand_total or 0)
    
    month_labels = list(monthly_revenue.keys())
    monthly_revenue_data = list(monthly_revenue.values())
    
    # Top destinations (from terms JSON)
    destinations = {}
    for inv in invoices:
        meta = {}
        if inv.terms:
            try:
                meta = json.loads(inv.terms)
            except:
                pass
        dest = meta.get('destination', 'Domestic')
        destinations[dest] = destinations.get(dest, 0) + 1
    
    top_destinations = [{'name': k, 'count': v} for k, v in sorted(destinations.items(), key=lambda x: x[1], reverse=True)[:5]]
    
    # Top products from invoice items
    products = {}
    for inv in invoices:
        for item in inv.items:
            name = item.description or item.code or 'Unknown'
            products[name] = products.get(name, 0) + float(item.qty or 0)
    
    top_products = [{'name': k, 'qty': v} for k, v in sorted(products.items(), key=lambda x: x[1], reverse=True)[:5]]
    
    # Top customers
    customers = {}
    for inv in invoices:
        name = inv.client_obj.name if inv.client_obj else (inv.contact_person or 'Unknown')
        customers[name] = customers.get(name, 0) + float(inv.grand_total or 0)
    
    top_customers = [{'name': k, 'amount': v} for k, v in sorted(customers.items(), key=lambda x: x[1], reverse=True)[:5]]
    
    # Status counts
    paid_count = sum(1 for i in invoices if i.status == 'Paid')
    partial_count = sum(1 for i in invoices if i.status == 'Partial')
    pending_count = sum(1 for i in invoices if i.status not in ['Paid', 'Partial'])
    
    # Invoice list for table
    invoice_list = []
    for inv in invoices[:50]:
        meta = {}
        if inv.terms:
            try:
                meta = json.loads(inv.terms)
            except:
                pass
        invoice_list.append({
            'id': inv.invoice_id,
            'date': inv.date.strftime('%d %b %Y'),
            'customer': inv.client_obj.name if inv.client_obj else (inv.contact_person or '—'),
            'destination': meta.get('destination', '—'),
            'subtotal': float(inv.subtotal or 0),
            'tax': float(inv.tax_amount or 0),
            'total': float(inv.grand_total or 0),
            'status': inv.status or 'Pending'
        })
    
    return jsonify({
        'total_revenue': total_revenue,
        'total_tax': total_tax,
        'total_received': total_received,
        'total_pending': total_pending,
        'total_invoices': len(invoices),
        'month_labels': month_labels,
        'monthly_revenue': monthly_revenue_data,
        'top_destinations': top_destinations,
        'top_products': top_products,
        'top_customers': top_customers,
        'paid_count': paid_count,
        'partial_count': partial_count,
        'pending_count': pending_count,
        'invoices': invoice_list
    })


@app.route("/api/reports/purchase-data")
@login_required
def api_purchase_report_data():
    """API endpoint for purchase report data"""
    cdb = get_cdb()
    if not cdb:
        return jsonify({"error": "Could not connect to company database"}), 500
    
    company_id = get_current_company()
    
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    
    if not from_date_str:
        from_date = date(2000, 1, 1)   # Show all records by default
    else:
        from_date = date.fromisoformat(from_date_str)
    
    if not to_date_str:
        to_date = date.today()
    else:
        to_date = date.fromisoformat(to_date_str)

    purchases = cdb.query(PurchaseInvoice).filter(
        PurchaseInvoice.company_id == company_id,
        PurchaseInvoice.date >= from_date,
        PurchaseInvoice.date <= to_date
    ).order_by(PurchaseInvoice.date.desc()).all()
    
    total_amount = sum(float(p.grand_total or 0) for p in purchases)
    total_gst = sum(float(p.tax_amount or 0) for p in purchases)
    total_paid = sum(float(p.paid_amount or 0) for p in purchases)
    total_pending = sum(float(p.balance or 0) for p in purchases)
    
    # Unique supplier count
    supplier_ids = set()
    for p in purchases:
        if p.supplier_id:
            supplier_ids.add(p.supplier_id)
    supplier_count = len(supplier_ids)
    
    # Monthly trend
    monthly_purchases = {}
    for p in purchases:
        month_key = p.date.strftime('%b %Y')
        monthly_purchases[month_key] = monthly_purchases.get(month_key, 0) + float(p.grand_total or 0)
    
    month_labels = list(monthly_purchases.keys())
    monthly_purchases_data = list(monthly_purchases.values())
    
    # Top suppliers
    suppliers = {}
    for p in purchases:
        try:
            name = p.supplier.name if p.supplier else (getattr(p, 'supplier_name', None) or 'Unknown')
        except Exception:
            name = getattr(p, 'supplier_name', None) or 'Unknown'
        suppliers[name] = suppliers.get(name, 0) + float(p.grand_total or 0)
    
    top_suppliers = [{'name': k, 'amount': v} for k, v in sorted(suppliers.items(), key=lambda x: x[1], reverse=True)[:5]]
    
    # Top purchased products
    products = {}
    for p in purchases:
        for item in p.items:
            name = item.description or 'Unknown'
            products[name] = products.get(name, 0) + float(item.quantity or 0)
    
    top_products = [{'name': k, 'qty': v} for k, v in sorted(products.items(), key=lambda x: x[1], reverse=True)[:5]]
    
    # Status counts
    paid_count = sum(1 for p in purchases if p.status == 'Paid')
    partial_count = sum(1 for p in purchases if p.status == 'Partial')
    pending_count = sum(1 for p in purchases if p.status not in ['Paid', 'Partial'])
    
    invoice_list = []
    for p in purchases[:50]:
        try:
            sup_name = p.supplier.name if p.supplier else (getattr(p, 'supplier_name', None) or '—')
        except Exception:
            sup_name = getattr(p, 'supplier_name', None) or '—'
        invoice_list.append({
            'id': p.invoice_id,
            'date': p.date.strftime('%d %b %Y'),
            'supplier': sup_name,
            'subtotal': float(p.subtotal or 0),
            'tax': float(p.tax_amount or 0),
            'total': float(p.grand_total or 0),
            'status': p.status or 'Pending'
        })
    
    return jsonify({
        'total_amount': total_amount,
        'total_gst': total_gst,
        'total_paid': total_paid,
        'total_pending': total_pending,
        'supplier_count': supplier_count,
        'month_labels': month_labels,
        'monthly_purchases': monthly_purchases_data,
        'top_suppliers': top_suppliers,
        'top_products': top_products,
        'paid_count': paid_count,
        'partial_count': partial_count,
        'pending_count': pending_count,
        'invoices': invoice_list
    })

@app.route("/api/reports/stock-data")
@login_required
def api_stock_report_data():
    """API endpoint for stock report data - reads directly from StockItem table"""
    cdb = get_cdb()
    if not cdb:
        return jsonify({"error": "Could not connect to company database"}), 500
    
    company_id = get_current_company()
    
    # Get ALL stock items directly from StockItem table
    stock_items = cdb.query(StockItem).filter_by(company_id=company_id).all()
    
    total_items = len(stock_items)
    
    # Calculate total value using purchase_rate or unit_price
    total_value = 0
    in_stock = 0
    low_stock = 0
    out_stock = 0
    
    categories = {}
    stock_list = []
    
    for s in stock_items:
        qty = float(s.quantity or 0)
        price = float(s.purchase_rate or s.unit_price or 0)
        total_value += price * qty
        
        # Status
        reorder = float(s.reorder_level or 10)
        if qty <= 0:
            out_stock += 1
            status = 'out'
            status_label = 'Out of Stock'
        elif qty <= reorder:
            low_stock += 1
            status = 'low'
            status_label = 'Low Stock'
        else:
            in_stock += 1
            status = 'in'
            status_label = 'In Stock'
        
        # Category
        cat = s.category or 'Uncategorized'
        categories[cat] = categories.get(cat, 0) + 1
        
        stock_list.append({
            'code': s.code,
            'name': s.name,
            'category': s.category or '—',
            'quantity': int(qty),
            'price': price,
            'total': price * qty,
            'status': status,
            'status_label': status_label,
            'unit': s.unit or 'pcs',
            'reorder_level': int(reorder)
        })
    
    # Top selling items (from InvoiceItem table - sales data)
    top_selling = {}
    invoices = cdb.query(Invoice).filter_by(company_id=company_id).all()
    for inv in invoices:
        for item in inv.items:
            name = item.description or item.code or 'Unknown'
            top_selling[name] = top_selling.get(name, 0) + float(item.qty or 0)
    
    top_selling_list = [{'name': k, 'qty': v} for k, v in sorted(top_selling.items(), key=lambda x: x[1], reverse=True)[:10]]
    
    return jsonify({
        'total_items': total_items,
        'total_value': total_value,
        'in_stock': in_stock,
        'low_stock': low_stock,
        'out_stock': out_stock,
        'category_count': len(categories),
        'categories': [{'name': k, 'count': v} for k, v in categories.items()],
        'top_selling': top_selling_list,
        'stock_items': stock_list
    })

@app.route("/api/reports/tax-data")
@login_required
def api_tax_report_data():
    cdb = get_cdb()
    if not cdb:
        return jsonify({"error": "Could not connect to company database"}), 500
    
    company_id = get_current_company()
    
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    
    if not from_date_str:
        from_date = date.today().replace(day=1)
    else:
        from_date = date.fromisoformat(from_date_str)
    
    if not to_date_str:
        to_date = date.today()
    else:
        to_date = date.fromisoformat(to_date_str)
    
    sales = cdb.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.date >= from_date,
        Invoice.date <= to_date,
        Invoice.status.notin_(['Cancelled', 'Void'])
    ).all()
    
    purchases = cdb.query(PurchaseInvoice).filter(
        PurchaseInvoice.company_id == company_id,
        PurchaseInvoice.date >= from_date,
        PurchaseInvoice.date <= to_date
    ).all()
    
    output_gst = sum(float(i.tax_amount or 0) for i in sales)
    input_gst = sum(float(p.tax_amount or 0) for p in purchases)
    net_gst = output_gst - input_gst
    
    total_sales = sum(float(i.grand_total or 0) for i in sales)
    effective_rate = (net_gst / total_sales * 100) if total_sales > 0 else 0
    
    # Monthly GST
    monthly_gst = {}
    for inv in sales:
        month_key = inv.date.strftime('%b %Y')
        monthly_gst[month_key] = monthly_gst.get(month_key, 0) + float(inv.tax_amount or 0)
    
    # HSN Summary
    hsn_summary = []
    hsn_dict = {}
    for inv in sales:
        for item in inv.items:
            hsn = (item.code or 'Other')[:6] if item.code else 'Other'
            if hsn not in hsn_dict:
                hsn_dict[hsn] = {'hsn': hsn, 'description': item.description or '', 'quantity': 0, 'value': 0, 'rate': 18, 'cgst': 0, 'sgst': 0, 'total': 0}
            qty = float(item.qty or 0)
            rate = float(item.rate or 0)
            amount = qty * rate
            gst = amount * 0.18
            hsn_dict[hsn]['quantity'] += qty
            hsn_dict[hsn]['value'] += amount
            hsn_dict[hsn]['cgst'] += gst / 2
            hsn_dict[hsn]['sgst'] += gst / 2
            hsn_dict[hsn]['total'] += gst
    hsn_summary = list(hsn_dict.values())
    
    return jsonify({
        'output_gst': output_gst,
        'input_gst': input_gst,
        'net_gst': net_gst,
        'effective_rate': round(effective_rate, 2),
        'month_labels': list(monthly_gst.keys()),
        'monthly_gst': list(monthly_gst.values()),
        'cgst': output_gst / 2,
        'sgst': output_gst / 2,
        'igst': 0,
        'hsn_summary': hsn_summary
    })


@app.route("/api/reports/financial-data")
@login_required
def api_financial_report_data():
    """API endpoint for financial report data"""
    cdb = get_cdb()
    if not cdb:
        return jsonify({"error": "Could not connect to company database"}), 500
    
    company_id = get_current_company()
    
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    
    if not from_date_str:
        from_date = date.today().replace(day=1)
    else:
        from_date = date.fromisoformat(from_date_str)
    
    if not to_date_str:
        to_date = date.today()
    else:
        to_date = date.fromisoformat(to_date_str)
    
    # ── INCOME ───────────────────────────────────────────────────────────────
    # 1. Sales Revenue
    sales = cdb.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.date >= from_date,
        Invoice.date <= to_date,
        Invoice.status.notin_(['Cancelled', 'Void'])
    ).all()
    sales_income = sum(float(i.grand_total or 0) for i in sales)
    
    # 2. Other Income (Cash Transactions - income type)
    other_income = cdb.query(CashTransaction).filter(
        CashTransaction.company_id == company_id,
        CashTransaction.type == 'income',
        CashTransaction.date >= from_date,
        CashTransaction.date <= to_date
    ).all()
    other_income_total = sum(t.amount for t in other_income)
    
    total_income = sales_income + other_income_total
    
    # ── EXPENSES ─────────────────────────────────────────────────────────────
    # 1. Cost of Goods Sold (Purchases)
    purchases = cdb.query(PurchaseInvoice).filter(
        PurchaseInvoice.company_id == company_id,
        PurchaseInvoice.date >= from_date,
        PurchaseInvoice.date <= to_date
    ).all()
    purchase_expense = sum(float(p.grand_total or 0) for p in purchases)
    
    # 2. Operating Expenses (from Expense table) ← FIXED!
    operating_expenses = cdb.query(Expense).filter(
        Expense.company_id == company_id,
        Expense.date >= from_date,
        Expense.date <= to_date
    ).all()
    operating_expense_total = sum(e.amount for e in operating_expenses)
    
    # 3. Cash Transaction Expenses (if any - but these should be in Expense table)
    cash_expenses = cdb.query(CashTransaction).filter(
        CashTransaction.company_id == company_id,
        CashTransaction.type == 'expense',
        CashTransaction.date >= from_date,
        CashTransaction.date <= to_date
    ).all()
    cash_expense_total = sum(t.amount for t in cash_expenses)
    
    # Total Expenses = Purchases + Operating Expenses + Cash Expenses
    total_expenses = purchase_expense + operating_expense_total + cash_expense_total
    
    # ── PROFIT ────────────────────────────────────────────────────────────────
    net_profit = total_income - total_expenses
    profit_margin = (net_profit / total_income * 100) if total_income > 0 else 0
    
    # ── MONTHLY BREAKDOWN ────────────────────────────────────────────────────
    monthly_income = {}
    monthly_expenses = {}
    
    # Monthly income from sales
    for inv in sales:
        month_key = inv.date.strftime('%b %Y')
        monthly_income[month_key] = monthly_income.get(month_key, 0) + float(inv.grand_total or 0)
    
    # Monthly expenses from purchases
    for p in purchases:
        month_key = p.date.strftime('%b %Y')
        monthly_expenses[month_key] = monthly_expenses.get(month_key, 0) + float(p.grand_total or 0)
    
    # Monthly expenses from Expense table ← FIXED!
    for e in operating_expenses:
        month_key = e.date.strftime('%b %Y')
        monthly_expenses[month_key] = monthly_expenses.get(month_key, 0) + e.amount
    
    # Monthly expenses from CashTransaction expenses
    for t in cash_expenses:
        month_key = t.date.strftime('%b %Y')
        monthly_expenses[month_key] = monthly_expenses.get(month_key, 0) + t.amount
    
    all_months = set(monthly_income.keys()) | set(monthly_expenses.keys())
    sorted_months = sorted(all_months, key=lambda x: datetime.strptime(x, '%b %Y'))
    
    monthly_profit = {}
    for m in sorted_months:
        monthly_profit[m] = monthly_income.get(m, 0) - monthly_expenses.get(m, 0)
    
    # ── CASH AND BANK BALANCES ──────────────────────────────────────────────
    # Cash balance from CashTransaction
    all_cash_txns = cdb.query(CashTransaction).filter_by(company_id=company_id).all()
    cash_balance = sum(t.amount for t in all_cash_txns if t.type == 'income') - sum(t.amount for t in all_cash_txns if t.type == 'expense')
    
    # Bank balance
    bank_accounts = cdb.query(BankAccount).filter_by(company_id=company_id, status='Active').all()
    bank_balance = sum(acc.balance for acc in bank_accounts)
    
    # ── EXPENSE BREAKDOWN BY CATEGORY ──────────────────────────────────────
    expense_breakdown = {}
    
    # From Expense table ← FIXED!
    for e in operating_expenses:
        expense_breakdown[e.category] = expense_breakdown.get(e.category, 0) + e.amount
    
    # Add purchases as a category
    if purchase_expense > 0:
        expense_breakdown['Purchases (COGS)'] = purchase_expense
    
    # Add cash expenses by category
    for t in cash_expenses:
        cat = t.category or 'Misc'
        expense_breakdown[cat] = expense_breakdown.get(cat, 0) + t.amount
    
    # ── CASH FLOW ENTRIES ────────────────────────────────────────────────────
    cashflow = []
    
    # Income entries
    for inv in sales[:20]:
        cashflow.append({
            'date': inv.date.strftime('%d %b %Y'),
            'type': 'income',
            'category': 'Sales',
            'description': f"Invoice {inv.invoice_id}",
            'amount': float(inv.grand_total or 0),
            'mode': 'Credit'
        })
    
    # Expense entries from Expense table ← FIXED!
    for e in operating_expenses[:20]:
        cashflow.append({
            'date': e.date.strftime('%d %b %Y'),
            'type': 'expense',
            'category': e.category,
            'description': e.description or e.category,
            'amount': e.amount,
            'mode': e.payment_mode or 'Cash'
        })
    
    # Cash transaction expenses
    for t in cash_expenses[:10]:
        cashflow.append({
            'date': t.date.strftime('%d %b %Y'),
            'type': 'expense',
            'category': t.category,
            'description': t.description,
            'amount': t.amount,
            'mode': 'Cash'
        })
    
    cashflow.sort(key=lambda x: x['date'], reverse=True)
    
    return jsonify({
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net_profit': net_profit,
        'profit_margin': round(profit_margin, 2),
        'month_labels': sorted_months,
        'monthly_income': [monthly_income.get(m, 0) for m in sorted_months],
        'monthly_expenses': [monthly_expenses.get(m, 0) for m in sorted_months],
        'monthly_profit': [monthly_profit.get(m, 0) for m in sorted_months],
        'cash_balance': cash_balance,
        'bank_balance': bank_balance,
        'expense_breakdown': expense_breakdown,
        'cashflow': cashflow
    })

@app.route("/reports/profit-loss")
@login_required
def profit_loss():
    """Profit & Loss Statement"""
    cdb = get_cdb()
    company_id = get_current_company()
    
    # Get filter parameters
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    period = request.args.get('period', 'custom')
    
    # Set date range based on period
    if period == 'month':
        from_date = date.today().replace(day=1)
        to_date = date.today()
    elif period == 'quarter':
        current_month = date.today().month
        if current_month <= 3:
            from_date = date(date.today().year, 1, 1)
        elif current_month <= 6:
            from_date = date(date.today().year, 4, 1)
        elif current_month <= 9:
            from_date = date(date.today().year, 7, 1)
        else:
            from_date = date(date.today().year, 10, 1)
        to_date = date.today()
    elif period == 'year':
        from_date = date(date.today().year, 1, 1)
        to_date = date.today()
    else:
        if not from_date_str:
            from_date = date.today().replace(day=1)
        else:
            from_date = date.fromisoformat(from_date_str)
        
        if not to_date_str:
            to_date = date.today()
        else:
            to_date = date.fromisoformat(to_date_str)
    
    # INCOME: Sales Revenue
    sales_invoices = cdb.query(Invoice).filter(
        Invoice.company_id == company_id,
        Invoice.date >= from_date,
        Invoice.date <= to_date,
        Invoice.status.notin_(['Cancelled', 'Void'])
    ).all()
    
    total_revenue = sum(i.grand_total or 0 for i in sales_invoices)
    
    # EXPENSES: Purchase Cost
    purchase_invoices = cdb.query(PurchaseInvoice).filter(
        PurchaseInvoice.company_id == company_id,
        PurchaseInvoice.date >= from_date,
        PurchaseInvoice.date <= to_date,
        PurchaseInvoice.status.notin_(['Cancelled', 'Void'])
    ).all()
    
    cost_of_goods_sold = sum(p.grand_total or 0 for p in purchase_invoices)
    
    # GROSS PROFIT
    gross_profit = total_revenue - cost_of_goods_sold
    
    # Calculate other income (cash transactions)
    cash_income = cdb.query(CashTransaction).filter(
        CashTransaction.company_id == company_id,
        CashTransaction.type == 'income',
        CashTransaction.date >= from_date,
        CashTransaction.date <= to_date
    ).all()
    other_income = sum(i.amount for i in cash_income)
    
    # Calculate expenses (cash transactions)
    cash_expenses = cdb.query(CashTransaction).filter(
        CashTransaction.company_id == company_id,
        CashTransaction.type == 'expense',
        CashTransaction.date >= from_date,
        CashTransaction.date <= to_date
    ).all()
    
    # Categorize expenses
    expense_categories = {}
    for exp in cash_expenses:
        if exp.category not in expense_categories:
            expense_categories[exp.category] = 0
        expense_categories[exp.category] += exp.amount
    
    total_expenses = sum(expense_categories.values())
    
    # NET PROFIT
    net_profit = gross_profit + other_income - total_expenses
    
    # Calculate ratios
    gross_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
    net_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0
    
    # Monthly profit trend
    monthly_profit = {}
    all_months = set()
    
    for inv in sales_invoices:
        month_key = inv.date.strftime('%Y-%m')
        all_months.add(month_key)
    
    for pur in purchase_invoices:
        month_key = pur.date.strftime('%Y-%m')
        all_months.add(month_key)
    
    for month in sorted(all_months):
        month_date = datetime.strptime(month, '%Y-%m')
        monthly_profit[month] = {
            'month': month_date.strftime('%b %Y'),
            'revenue': 0,
            'expenses': 0,
            'profit': 0
        }
    
    for inv in sales_invoices:
        month_key = inv.date.strftime('%Y-%m')
        monthly_profit[month_key]['revenue'] += inv.grand_total or 0
    
    for exp in cash_expenses:
        month_key = exp.date.strftime('%Y-%m')
        if month_key in monthly_profit:
            monthly_profit[month_key]['expenses'] += exp.amount
    
    for month in monthly_profit:
        monthly_profit[month]['profit'] = monthly_profit[month]['revenue'] - monthly_profit[month]['expenses']
    
    profit_trend = list(monthly_profit.values())
    
    return render_template("profit_loss.html",
                         active='profit_loss',
                         from_date=from_date,
                         to_date=to_date,
                         period=period,
                         total_revenue=total_revenue,
                         cost_of_goods_sold=cost_of_goods_sold,
                         gross_profit=gross_profit,
                         other_income=other_income,
                         expense_categories=expense_categories,
                         total_expenses=total_expenses,
                         net_profit=net_profit,
                         gross_margin=gross_margin,
                         net_margin=net_margin,
                         profit_trend=profit_trend,
                         today=date.today())

# ============================================
# SYNC, SHARE & BACKUP ROUTES
# ============================================

@app.route("/sync")
@login_required
def sync_data():
    """Sync data with cloud"""
    company_id = get_current_company()
    return render_template("sync.html", active='sync')



@app.route("/share")
@login_required
def share_data():
    """Share data with others"""
    company_id = get_current_company()
    return render_template("share.html", active='share')

# ============================================
# OTHER PRODUCTS ROUTES
# ============================================

@app.route("/integrations")
@login_required
def integrations():
    """Third-party integrations"""
    company_id = get_current_company()
    return render_template("integrations.html", active='integrations')

@app.route("/addons")
@login_required
def addons():
    """Add-ons marketplace"""
    company_id = get_current_company()
    return render_template("addons.html", active='addons')

# ============================================
# UTILITIES ROUTES
# ============================================

@app.route("/import")
@login_required
def import_data():
    """Import data from files"""
    company_id = get_current_company()
    return render_template("import.html", active='import')

@app.route("/export")
@login_required
def export_data():
    """Export data to files"""
    company_id = get_current_company()
    return render_template("export.html", active='export')

@app.route("/audit-log")
@login_required
def audit_log():
    """View audit logs"""
    company_id = get_current_company()
    return render_template("audit_log.html", active='audit')

# ─────────────────────────────────────────────────────────────────────────────
# ── Profile ───────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/profile")
@login_required
def profile():
    user = get_current_user()
    return render_template("profile.html", user=user)



# ─────────────────────────────────────────────────────────────────────────────
# ── Company Settings ──────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/company/settings")
@login_required
@owner_required
def company_settings():
    company_id = get_current_company()
    company = get_company_by_id(company_id)
    
    # Use customer database session to query CompanyUser
    cdb = get_cdb()
    if not cdb:
        flash("Could not connect to company database")
        return redirect(url_for("dashboard"))
    
    users = cdb.query(CompanyUser).filter_by(company_id=company_id).all()
    
    # Fix: Convert plans to a dictionary with proper structure
    plans = {}
    for p in SubscriptionPlan.query.all():
        plans[p.id] = {
            "name":          p.name,
            "price":         p.price,
            "max_companies": p.max_companies,
            "max_users":     p.max_users,
            "features":      p.features.split(",") if p.features else [],
        }
    
    current_plan = plans.get(company.subscription_plan) if company else None
    return render_template("company_settings.html",
                           company=company,
                           users=users,
                           plans=plans,
                           current_plan=current_plan)

@app.route("/company/update-info", methods=["POST"])
@login_required
@owner_required
def update_company_info():
    company_id = get_current_company()
    company    = get_company_by_id(company_id)
    if company:
        company.company_name = request.form.get("company_name", company.company_name).strip()
        company.address      = request.form.get("address",      company.address)
        company.phone        = request.form.get("phone",        company.phone)
        company.gst_number   = request.form.get("gst_number",   company.gst_number)
        cdb.commit()
        # Keep session in sync
        if "user" in session:
            session["user"]["company_name"] = company.company_name
            session.modified = True
        flash("Company information updated successfully.")
    else:
        flash("Company not found.")
    return redirect(url_for("company_settings"))


@app.route("/company/add-user", methods=["POST"])
@login_required
@owner_required
def add_company_user():
    cdb = get_cdb()
    company_id = get_current_company()

    can_add, message = check_company_limit(company_id, "user")
    if not can_add:
        flash(message)
        return redirect(url_for("company_settings"))

    email     = request.form.get("email",     "").strip().lower()
    password  = request.form.get("password",  "")
    full_name = request.form.get("full_name", "").strip()
    role      = request.form.get("role",      "employee")
    department= request.form.get("department","")
    phone     = request.form.get("phone",     "")

    if cdb.query(CompanyUser).filter_by(company_id=company_id, email=email).first():
        flash("A user with this email already exists in your company.")
        return redirect(url_for("company_settings"))

    emp_count = cdb.query(CompanyUser).count()
    emp_id    = f"EMP{emp_count + 1:03d}"
    new_user  = CompanyUser(
        user_id=emp_id, company_id=company_id,
        email=email, password_hash=hash_password(password),
        full_name=full_name, role=role,
        department=department, phone=phone,
        is_active=True, created_at=date.today()
    )
    cdb.add(new_user)
    cdb.commit()
    flash(f"User '{full_name}' added successfully.")
    return redirect(url_for("company_settings"))



@app.route("/company/remove-user/<user_id>")
@login_required
@owner_required
def remove_company_user(user_id):
    cdb = get_cdb()
    company_id = get_current_company()
    user = cdb.query(CompanyUser).filter_by(user_id=user_id, company_id=company_id).first()
    if user and user.role != "owner":
        user.is_active = False
        cdb.commit()
        flash("User removed successfully.")
    else:
        flash("Cannot remove this user.")
    return redirect(url_for("company_settings"))


@app.route("/company/upgrade-plan", methods=["POST"])
@login_required
@owner_required
def upgrade_plan():
    company_id = get_current_company()
    company    = get_company_by_id(company_id)
    new_plan   = request.form.get("plan")
    plan       = SubscriptionPlan.query.get(new_plan)
    if company and plan:
        company.subscription_plan     = new_plan
        company.max_users_per_company = plan.max_users
        company.max_companies_allowed = plan.max_companies
        cdb.commit()
        flash(f"Plan upgraded to {plan.name} successfully!")
    else:
        flash("Invalid plan selected.")
    return redirect(url_for("company_settings"))

# ─────────────────────────────────────────────────────────────────────────────
# ── DEBTORS & CREDITORS ───────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
def _debtor_summary(company_id):
    cdb = get_cdb()
    
    # FIX 2: Get ALL clients, not just those with invoices
    all_clients = cdb.query(Client).filter_by(company_id=company_id).order_by(Client.name).all()
    
    today = date.today()
    rows = []

    for c in all_clients:
        invoices = (cdb.query(Invoice)
                    .filter_by(company_id=company_id, client_id=c.id)
                    .order_by(Invoice.date.desc())
                    .all())
        
        # If no invoices, still show client with zero balance
        if not invoices:
            rows.append({
                "id":                c.id,
                "name":              c.name,
                "phone":             c.phone or "",
                "city":              c.city or "",
                "total_invoiced":    0,
                "total_paid":        0,
                "total_pending":     0,
                "last_invoice_date": None,
                "nearest_due_date":  None,
                "nearest_due_amt":   None,
                "last_payment_date": None,
                "last_payment_amt":  None,
                "invoice_count":     0,
                "overdue":           False,
                "status":            "Fully Paid" if c.pending == 0 else "Has Dues",
            })
            continue

        # Calculate totals
        total_pending = sum(float(getattr(i, "balance", 0) or 0) for i in invoices)
        total_invoiced = sum(float(i.grand_total or 0) for i in invoices)
        total_paid = total_invoiced - total_pending
        last_invoice_date = invoices[0].date

        # Calculate overdue
        unpaid = [i for i in invoices if (float(getattr(i, "balance", 0) or 0)) > 0]
        due_invoices = [i for i in unpaid if getattr(i, "due_date", None)]
        if due_invoices:
            future = [i for i in due_invoices if i.due_date >= today]
            nearest = min(future, key=lambda i: i.due_date) if future else \
                      max(due_invoices, key=lambda i: i.due_date)
            nearest_due_date = nearest.due_date
            nearest_due_amt = float(getattr(nearest, "balance", 0) or 0)
            overdue = nearest_due_date < today if nearest_due_date else False
        else:
            nearest_due_date = None
            nearest_due_amt = None
            overdue = False

        # Last payment
        paid_invoices = [i for i in invoices
                         if (float(i.grand_total or 0) - (float(getattr(i, "balance", 0) or 0))) > 0]
        if paid_invoices:
            last_paid_inv = max(paid_invoices, key=lambda i: i.date)
            last_payment_date = last_paid_inv.date
            last_payment_amt = float(last_paid_inv.grand_total or 0) - (float(getattr(last_paid_inv, "balance", 0) or 0))
        else:
            last_payment_date = None
            last_payment_amt = None

        rows.append({
            "id":                c.id,
            "name":              c.name,
            "phone":             c.phone or "",
            "city":              c.city or "",
            "total_invoiced":    total_invoiced,
            "total_paid":        total_paid,
            "total_pending":     total_pending,
            "last_invoice_date": last_invoice_date,
            "nearest_due_date":  nearest_due_date,
            "nearest_due_amt":   nearest_due_amt,
            "last_payment_date": last_payment_date,
            "last_payment_amt":  last_payment_amt,
            "invoice_count":     len(invoices),
            "overdue":           overdue,
            "status":            "Fully Paid" if total_pending == 0 else "Has Dues",
        })

    rows.sort(key=lambda r: r["total_pending"], reverse=True)
    return rows

def _creditor_summary(company_id):
    """
    Show ALL suppliers (creditors) - including those fully paid.
    For suppliers with no invoices or fully paid, show zero balance.
    """
    cdb = get_cdb()
    suppliers = cdb.query(Client).filter(
        Client.company_id == company_id,
        db.or_(Client.client_type == "Supplier", Client.client_type == "Both")
    ).order_by(Client.name).all()

    today = date.today()
    rows = []

    for s in suppliers:
        invoices = (cdb.query(PurchaseInvoice)
                    .filter_by(company_id=company_id, supplier_id=s.id)
                    .order_by(PurchaseInvoice.date.desc())
                    .all())
        
        # If no invoices, still show supplier with zero balance
        if not invoices:
            rows.append({
                "id":                s.id,
                "name":              s.name,
                "phone":             s.phone or "",
                "city":              s.city or "",
                "total_pending":     0,
                "last_bill_date":    None,
                "nearest_due_date":  None,
                "nearest_due_amt":   None,
                "last_payment_date": None,
                "last_payment_amt":  None,
                "invoice_count":     0,
                "overdue":           False,
                "status":            "Fully Paid",
            })
            continue

        total_pending = sum(i.balance or 0 for i in invoices)
        last_bill_date = invoices[0].date

        # Calculate overdue
        unpaid = [i for i in invoices if (i.balance or 0) > 0]
        due_invoices = [i for i in unpaid if i.due_date]
        if due_invoices:
            future = [i for i in due_invoices if i.due_date >= today]
            nearest = min(future, key=lambda i: i.due_date) if future else \
                      max(due_invoices, key=lambda i: i.due_date)
            nearest_due_date = nearest.due_date
            nearest_due_amt = nearest.balance or 0
            overdue = nearest_due_date < today if nearest_due_date else False
        else:
            nearest_due_date = None
            nearest_due_amt = None
            overdue = False

        # Last payment
        paid_invs = [i for i in invoices if (i.paid_amount or 0) > 0]
        if paid_invs:
            last_paid_inv = max(paid_invs, key=lambda i: i.date)
            last_payment_date = last_paid_inv.date
            last_payment_amt = last_paid_inv.paid_amount or 0
        else:
            last_payment_date = None
            last_payment_amt = None

        rows.append({
            "id":                s.id,
            "name":              s.name,
            "phone":             s.phone or "",
            "city":              s.city or "",
            "total_pending":     total_pending,
            "last_bill_date":    last_bill_date,
            "nearest_due_date":  nearest_due_date,
            "nearest_due_amt":   nearest_due_amt,
            "last_payment_date": last_payment_date,
            "last_payment_amt":  last_payment_amt,
            "invoice_count":     len(invoices),
            "overdue":           overdue,
            "status":            "Fully Paid" if total_pending == 0 else "Has Dues",
        })

    rows.sort(key=lambda r: r["total_pending"], reverse=True)
    return rows

@app.route("/debtors")
@login_required
def debtors_list():
    company_id        = get_current_company()
    debtors           = _debtor_summary(company_id)
    total_outstanding = sum(d["total_pending"] for d in debtors)
    overdue_count     = sum(1 for d in debtors if d["overdue"])
    return render_template("debtors.html",
                           debtors=debtors,
                           total_outstanding=total_outstanding,
                           overdue_count=overdue_count)


@app.route("/creditors")
@login_required
def creditors_list():
    company_id    = get_current_company()
    creditors     = _creditor_summary(company_id)
    total_payable = sum(c["total_pending"] for c in creditors)
    overdue_count = sum(1 for c in creditors if c["overdue"])
    return render_template("creditors.html",
                           creditors=creditors,
                           total_payable=total_payable,
                           overdue_count=overdue_count)


@app.route("/debtors/<int:client_pk>/statement")
@login_required
def debtor_statement(client_pk):
    cdb = get_cdb()
    company_id = get_current_company()
    c = _first_or_404(cdb.query(Client).filter_by(id=client_pk, company_id=company_id).first())

    invoices = (cdb.query(Invoice)
                .filter_by(company_id=company_id, client_id=c.id)
                .order_by(Invoice.date.asc())
                .all())

    ledger = []
    running_balance = c.opening_balance or 0.0

    if running_balance:
        ledger.append({
            "date":    c.created_at or date.today(),
            "type":    "Opening Balance",
            "ref":     "—",
            "debit":   running_balance,
            "credit":  0,
            "balance": running_balance,
            "status":  "",
            "id":      None,
        })

    for inv in invoices:
        # Add invoice
        running_balance += inv.grand_total
        ledger.append({
            "date":    inv.date,
            "type":    "Invoice",
            "ref":     inv.invoice_id,
            "debit":   inv.grand_total,
            "credit":  0,
            "balance": running_balance,
            "status":  inv.status,  # Shows Paid/Partial/Draft
            "id":      inv.invoice_id,
        })
        
        # Add payment if any was made
        paid = (inv.grand_total or 0) - (getattr(inv, "balance", 0) or 0)
        if paid > 0:
            running_balance -= paid
            ledger.append({
                "date":    inv.date,  # Use payment date if you have it
                "type":    "Payment Received",
                "ref":     inv.invoice_id,
                "debit":   0,
                "credit":  paid,
                "balance": running_balance,
                "status":  "",
                "id":      inv.invoice_id,
            })

    total_debit = sum(r["debit"] for r in ledger)
    total_credit = sum(r["credit"] for r in ledger)

    return render_template("ledger_statement.html",
                           entity=_normalize_client(c),
                           ledger=ledger,
                           total_debit=total_debit,
                           total_credit=total_credit,
                           closing_balance=running_balance,
                           mode="debtor",
                           back_url="/debtors",
                           today=date.today().strftime("%d %b %Y"))


@app.route("/creditors/<int:supplier_pk>/statement")
@login_required
def creditor_statement(supplier_pk):
    cdb = get_cdb()
    company_id = get_current_company()
    s          = _first_or_404(cdb.query(Client).filter_by(id=supplier_pk, company_id=company_id).first())

    invoices = (cdb.query(PurchaseInvoice)
                .filter_by(company_id=company_id, supplier_id=s.id)
                .order_by(PurchaseInvoice.date.asc())
                .all())

    ledger          = []
    running_balance = s.opening_balance or 0.0

    if running_balance:
        ledger.append({
            "date":    s.created_at or date.today(),
            "type":    "Opening Balance",
            "ref":     "—",
            "debit":   0,
            "credit":  running_balance,
            "balance": running_balance,
            "status":  "",
            "id":      None,
            "inv_id":  None,
        })

    for inv in invoices:
        running_balance += inv.grand_total
        ledger.append({
            "date":    inv.date,
            "type":    "Purchase Invoice",
            "ref":     inv.invoice_number or inv.invoice_id,
            "debit":   0,
            "credit":  inv.grand_total,
            "balance": running_balance,
            "status":  inv.status,
            "id":      inv.id,
            "inv_id":  inv.invoice_id,
        })
        if inv.paid_amount and inv.paid_amount > 0:
            running_balance -= inv.paid_amount
            ledger.append({
                "date":    inv.date,
                "type":    "Payment Made",
                "ref":     inv.invoice_number or inv.invoice_id,
                "debit":   inv.paid_amount,
                "credit":  0,
                "balance": running_balance,
                "status":  "",
                "id":      inv.id,
                "inv_id":  inv.invoice_id,
            })

    total_debit  = sum(r["debit"]  for r in ledger)
    total_credit = sum(r["credit"] for r in ledger)

    return render_template("ledger_statement.html",
                           entity=_normalize_client(s),
                           ledger=ledger,
                           total_debit=total_debit,
                           total_credit=total_credit,
                           closing_balance=running_balance,
                           mode="creditor",
                           back_url="/creditors",
                           today=date.today().strftime("%d %b %Y"))


# ─────────────────────────────────────────────────────────────────────────────
# ── Receipts & Payments ───────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def _outstanding_invoices_for_client(company_id, client_id):
    """Return list of dicts for invoices with a remaining balance for a client."""
    cdb = get_cdb()
    invs = (cdb.query(Invoice)
            .filter_by(company_id=company_id, client_id=client_id)
            .filter(Invoice.status.in_(["Draft", "Partial"]))
            .order_by(Invoice.date.asc())
            .all())
    result = []
    for inv in invs:
        total   = inv.grand_total or 0
        balance = getattr(inv, "balance", None)
        if balance is None:
            balance = total if inv.status != "Paid" else 0
        if balance > 0:
            result.append({
                "id":      inv.id,
                "ref":     inv.invoice_id,
                "date":    inv.date.strftime("%d %b %Y") if inv.date else "",
                "total":   total,
                "balance": balance,
            })
    return result


def _outstanding_invoices_for_supplier(company_id, supplier_id):
    """Return list of dicts for purchase invoices with a remaining balance."""
    cdb = get_cdb()
    invs = (cdb.query(PurchaseInvoice)
            .filter_by(company_id=company_id, supplier_id=supplier_id)
            .filter(PurchaseInvoice.status.in_(["Pending", "Partial"]))
            .order_by(PurchaseInvoice.date.asc())
            .all())
    result = []
    for inv in invs:
        total   = inv.grand_total or 0
        balance = inv.balance or total
        if balance > 0:
            result.append({
                "id":      inv.id,
                "ref":     inv.invoice_number or inv.invoice_id,
                "date":    inv.date.strftime("%d %b %Y") if inv.date else "",
                "total":   total,
                "balance": balance,
            })
    return result


def _build_invoices_json(company_id, entities, fetch_fn):
    """Build {entity_id: [invoice list]} dict for JS."""
    data = {}
    for e in entities:
        data[str(e.id)] = fetch_fn(company_id, e.id)
    return json.dumps(data)


@app.route("/receipts/new")
@login_required
def receipt_new():
    cdb = get_cdb()
    company_id    = get_current_company()
    all_clients   = cdb.query(Client).filter_by(company_id=company_id).order_by(Client.name).all()
    selected_id   = request.args.get("client_id", type=int)
    invoices_json = _build_invoices_json(company_id, all_clients,
                                         _outstanding_invoices_for_client)
    return render_template(
        "receipt_payment.html",
        mode="receipt",
        entities=all_clients,
        invoices_json=invoices_json,
        selected_id=selected_id,
        today=str(date.today()),
    )


@app.route("/receipts/save", methods=["POST"])
@login_required
def receipt_save():
    cdb = get_cdb()
    company_id  = get_current_company()
    entity_id   = request.form.get("entity_id", type=int)
    amount      = request.form.get("amount", type=float, default=0)
    invoice_ids = [int(x) for x in request.form.get("invoice_ids", "").split(",") if x.strip()]
    narration   = request.form.get("narration", "")
    pay_mode    = request.form.get("pay_mode", "Cash")
    txn_date_str = request.form.get("txn_date")
    txn_date    = date.fromisoformat(txn_date_str) if txn_date_str else date.today()

    if not entity_id or amount <= 0:
        flash("Please select a client and enter a valid amount.")
        return redirect(url_for("receipt_new"))

    if not invoice_ids:
        rows = _outstanding_invoices_for_client(company_id, entity_id)
        invoice_ids = [r["id"] for r in rows]

    remaining = amount
    settled   = 0

    for inv_id in invoice_ids:
        if remaining <= 0:
            break
        inv = cdb.query(Invoice).filter_by(id=inv_id, company_id=company_id).first()
        if not inv:
            continue

        inv_balance = getattr(inv, "balance", None)
        if inv_balance is None:
            inv_balance = inv.grand_total or 0

        apply        = min(remaining, inv_balance)
        remaining   -= apply
        inv_balance -= apply
        settled     += apply

        if hasattr(inv, "balance"):
            inv.balance = inv_balance
        if hasattr(inv, "paid_amount"):
            inv.paid_amount = (inv.paid_amount or 0) + apply

        # FIX 1: Update status correctly
        if inv_balance <= 0:
            inv.status = "Paid"
        elif apply > 0:
            inv.status = "Partial"

        # Record payment in cash/bank
        if apply > 0:
            if pay_mode == "cash":
                cash_txn = CashTransaction(
                    company_id=company_id,
                    type="income",
                    date=txn_date,
                    category="Receipt",
                    description=f"Payment received for invoice {inv.invoice_id} - {narration}",
                    amount=apply,
                    reference=inv.invoice_id,
                    notes=f"Payment from client via {pay_mode}",
                    created_by=get_current_user().get('email')
                )
                cdb.add(cash_txn)
            else:
                # For bank/UPI/cheque payments, record in bank account
                bank_account = cdb.query(BankAccount).filter_by(
                    company_id=company_id, status='Active'
                ).first()
                if bank_account:
                    bank_txn = BankTransaction(
                        bank_account_id=bank_account.id,
                        company_id=company_id,
                        type="credit",
                        date=txn_date,
                        description=f"Payment received for invoice {inv.invoice_id}",
                        amount=apply,
                        reference=inv.invoice_id,
                        transaction_mode=pay_mode.title(),
                        notes=narration,
                        created_by=get_current_user().get('email')
                    )
                    cdb.add(bank_txn)
                    bank_account.balance += apply

    client = cdb.query(Client).filter_by(id=entity_id, company_id=company_id).first()
    if client and hasattr(client, "pending") and client.pending:
        client.pending = max(0, (client.pending or 0) - settled)

    cdb.commit()
    flash(f"Receipt of ₹{settled:,.2f} recorded via {pay_mode}. {narration}")
    return redirect(url_for("debtors_list"))


@app.route("/payments/new")
@login_required
def payment_new():
    cdb = get_cdb()
    company_id    = get_current_company()
    all_suppliers = cdb.query(Client).filter(
        Client.company_id == company_id,
        Client.client_type.in_(["Supplier", "Both"])
    ).order_by(Client.name).all()
    selected_id   = request.args.get("supplier_id", type=int)
    invoices_json = _build_invoices_json(company_id, all_suppliers,
                                         _outstanding_invoices_for_supplier)
    return render_template(
        "receipt_payment.html",
        mode="payment",
        entities=all_suppliers,
        invoices_json=invoices_json,
        selected_id=selected_id,
        today=str(date.today()),
    )


@app.route("/payments/save", methods=["POST"])
@login_required
def payment_save():
    cdb = get_cdb()
    company_id  = get_current_company()
    entity_id   = request.form.get("entity_id", type=int)
    amount      = request.form.get("amount", type=float, default=0)
    invoice_ids = [int(x) for x in request.form.get("invoice_ids", "").split(",") if x.strip()]
    narration   = request.form.get("narration", "")
    pay_mode    = request.form.get("pay_mode", "Cash")
    txn_date_str = request.form.get("txn_date")
    txn_date    = date.fromisoformat(txn_date_str) if txn_date_str else date.today()

    if not entity_id or amount <= 0:
        flash("Please select a supplier and enter a valid amount.")
        return redirect(url_for("payment_new"))

    if not invoice_ids:
        rows = _outstanding_invoices_for_supplier(company_id, entity_id)
        invoice_ids = [r["id"] for r in rows]

    remaining = amount
    settled   = 0

    for inv_id in invoice_ids:
        if remaining <= 0:
            break
        inv = cdb.query(PurchaseInvoice).filter_by(id=inv_id, company_id=company_id).first()
        if not inv:
            continue

        inv_balance  = inv.balance or (inv.grand_total or 0)
        apply        = min(remaining, inv_balance)
        remaining   -= apply
        settled     += apply

        inv.balance     = inv_balance - apply
        inv.paid_amount = (inv.paid_amount or 0) + apply

        # Update status correctly
        if inv.balance <= 0:
            inv.status = "Paid"
        elif inv.paid_amount > 0:
            inv.status = "Partial"
        else:
            inv.status = "Pending"

        # Log payment in cash/bank transactions
        if pay_mode == "cash":
            cash_txn = CashTransaction(
                company_id=company_id,
                type="expense",
                date=txn_date,
                category="Payment",
                description=f"Payment made for purchase invoice {inv.invoice_number or inv.invoice_id} - {narration}",
                amount=apply,
                reference=inv.invoice_id,
                notes=f"Payment to supplier via {pay_mode}",
                created_by=get_current_user().get('email')
            )
            cdb.add(cash_txn)
        else:
            # For bank/UPI/cheque payments
            bank_account = cdb.query(BankAccount).filter_by(
                company_id=company_id, status='Active'
            ).first()
            if bank_account:
                bank_txn = BankTransaction(
                    bank_account_id=bank_account.id,
                    company_id=company_id,
                    type="debit",
                    date=txn_date,
                    description=f"Payment made for purchase invoice {inv.invoice_number or inv.invoice_id}",
                    amount=apply,
                    reference=inv.invoice_id,
                    transaction_mode=pay_mode.title(),
                    notes=narration,
                    created_by=get_current_user().get('email')
                )
                cdb.add(bank_txn)
                bank_account.balance -= apply

        # Update supplier pending amount
        if inv.supplier:
            inv.supplier.pending = max(0, (inv.supplier.pending or 0) - apply)

    cdb.commit()
    flash(f"Payment of ₹{settled:,.2f} recorded via {pay_mode}. {narration}")
    return redirect(url_for("creditors_list"))

# ─────────────────────────────────────────────────────────────────────────────
# ── Backup & Restore Routes ───────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/backup")
@login_required
def backup():
    """Backup management page"""
    company_id = get_current_company()
    
    # Define backup destinations (fallback)
    backup_destinations = {
        "local": "Local Storage",
        "s3": "Amazon S3",
        "gcs": "Google Cloud Storage",
        "ftp": "FTP/SFTP Server",
    }
    
    backups = []
    
    try:
        from backup_utils import list_backups, BACKUP_DESTINATIONS
        backups = list_backups(company_id)
        backup_destinations = BACKUP_DESTINATIONS
    except ImportError as e:
        print(f"Could not import backup_utils: {e}")
        flash("Backup utilities not fully configured. Some features may be limited.", "warning")
    except Exception as e:
        print(f"Error loading backups: {e}")
        flash(f"Error loading backups: {str(e)}", "error")
    
    return render_template("backup.html", 
                         active='backup',
                         backups=backups,
                         backup_destinations=backup_destinations)
                         

@app.route("/backup/create", methods=["POST"])
@login_required
def create_backup():
    """Create a new backup"""
    company_id = get_current_company()
    include_attachments = request.form.get("include_attachments", "true") == "true"
    
    try:
        from backup_utils import create_company_backup, BACKUP_DESTINATIONS
        
        backup_info = create_company_backup(company_id, include_attachments)
        
        flash(f"Backup created successfully! File size: {backup_info['size_mb']} MB", "success")
        
        # Optionally upload to cloud
        if request.form.get("upload_to_cloud"):
            destination = request.form.get("cloud_destination")
            config = {
                'access_key': request.form.get('access_key'),
                'secret_key': request.form.get('secret_key'),
                'bucket': request.form.get('bucket'),
                'region': request.form.get('region', 'us-east-1')
            }
            from backup_utils import upload_backup_to_cloud
            upload_backup_to_cloud(backup_info['backup_id'], destination, config)
            flash("Backup also uploaded to cloud storage!", "success")
            
    except Exception as e:
        flash(f"Backup failed: {str(e)}", "error")
    
    return redirect(url_for("backup"))

@app.route("/backup/restore/<backup_id>", methods=["POST"])
@login_required
def restore_backup(backup_id):
    """Restore from a backup"""
    company_id = get_current_company()
    user = get_current_user()
    
    try:
        from backup_utils import restore_from_backup
        result = restore_from_backup(backup_id, user.get('email'))
        
        flash(f"Restore completed successfully! Company data restored from backup {backup_id}", "success")
        
    except Exception as e:
        flash(f"Restore failed: {str(e)}", "error")
    
    return redirect(url_for("backup"))

@app.route("/backup/download/<backup_id>")
@login_required
def download_backup(backup_id):
    """Download backup file"""
    company_id = get_current_company()
    
    from platform_models import BackupRecord
    backup = BackupRecord.query.filter_by(backup_id=backup_id, company_id=company_id).first()
    
    if not backup or not os.path.exists(backup.backup_file_path):
        flash("Backup file not found", "error")
        return redirect(url_for("backup"))
    
    return send_file(
        backup.backup_file_path,
        as_attachment=True,
        download_name=f"{backup_id}.zip"
    )

@app.route("/backup/delete/<backup_id>", methods=["POST"])
@login_required
def delete_backup_record(backup_id):
    """Delete a backup"""
    company_id = get_current_company()
    
    try:
        from backup_utils import delete_backup
        if delete_backup(backup_id):
            flash("Backup deleted successfully", "success")
        else:
            flash("Backup not found", "error")
    except Exception as e:
        flash(f"Error deleting backup: {str(e)}", "error")
    
    return redirect(url_for("backup"))

@app.route("/backup/schedule", methods=["POST"])
@login_required
def schedule_backup():
    """Schedule automatic backups"""
    company_id = get_current_company()
    
    frequency = request.form.get("frequency")
    time_of_day = request.form.get("time_of_day")
    retention_days = request.form.get("retention_days", 30)
    upload_to_cloud = request.form.get("upload_to_cloud") == "true"
    
    from platform_models import BackupSchedule
    
    # Save schedule to database
    schedule = BackupSchedule.query.filter_by(company_id=company_id).first()
    
    if not schedule:
        schedule = BackupSchedule(company_id=company_id)
        db.session.add(schedule)
    
    schedule.frequency = frequency
    schedule.time_of_day = time_of_day
    schedule.retention_days = int(retention_days)
    schedule.upload_to_cloud = upload_to_cloud
    schedule.last_backup = None
    
    # Calculate next backup
    from datetime import datetime, timedelta
    now = datetime.now()
    hour, minute = map(int, time_of_day.split(':'))
    
    if frequency == "daily":
        next_date = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_date <= now:
            next_date += timedelta(days=1)
    elif frequency == "weekly":
        days_ahead = 6 - now.weekday()
        next_date = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    elif frequency == "monthly":
        next_date = now.replace(day=1, hour=hour, minute=minute, second=0, microsecond=0)
        if next_date <= now:
            if next_date.month == 12:
                next_date = next_date.replace(year=next_date.year + 1, month=1)
            else:
                next_date = next_date.replace(month=next_date.month + 1)
    else:
        next_date = now + timedelta(days=1)
    
    schedule.next_backup = next_date
    schedule.is_active = True
    
    db.session.commit()
    flash(f"Automatic backup scheduled {frequency} at {time_of_day}", "success")
    
    return redirect(url_for("backup"))

@app.route("/backup/upload-to-cloud/<backup_id>", methods=["POST"])
@login_required
def upload_backup_to_cloud_route(backup_id):
    """Upload existing backup to cloud"""
    company_id = get_current_company()
    
    destination = request.form.get("destination")
    config = {
        'access_key': request.form.get('access_key'),
        'secret_key': request.form.get('secret_key'),
        'bucket': request.form.get('bucket'),
        'region': request.form.get('region', 'us-east-1'),
        'host': request.form.get('host'),
        'port': request.form.get('port', 22),
        'username': request.form.get('username'),
        'password': request.form.get('password'),
        'path': request.form.get('path', '/'),
        'credentials_file': request.form.get('credentials_file'),
    }
    
    try:
        from backup_utils import upload_backup_to_cloud
        upload_backup_to_cloud(backup_id, destination, config)
        flash("Backup uploaded to cloud successfully!", "success")
    except Exception as e:
        flash(f"Cloud upload failed: {str(e)}", "error")
    
    return redirect(url_for("backup"))

# Start backup scheduler
try:
    from backup_scheduler import start_backup_scheduler
    start_backup_scheduler()
except Exception as e:
    print(f"Could not start backup scheduler: {e}")




# ─────────────────────────────────────────────────────────────────────────────
# ── App entry point ───────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed_database()  # Only platform data
        
        # Seed customer databases for existing companies
        companies = Company.query.all()
        for company in companies:
            try:
                seed_customer_database(company.company_id)
            except Exception as e:
                print(f"Could not seed customer DB for {company.company_id}: {e}")
    app.run(debug=True, port=5010)
else:
    # When run by Gunicorn / Render, seed after the app is fully loaded
    with app.app_context():
        seed_database()  # Only platform data
        
        # Seed customer databases for existing companies
        companies = Company.query.all()
        for company in companies:
            try:
                seed_customer_database(company.company_id)
            except Exception as e:
                print(f"Could not seed customer DB for {company.company_id}: {e}")
