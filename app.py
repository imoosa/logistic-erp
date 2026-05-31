from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import date, datetime, timedelta
import random
import hashlib
import secrets
from functools import wraps
import os
import json
import re
from werkzeug.utils import secure_filename
import io
import base64
from sqlalchemy import text
from models import (
    db,
    SubscriptionPlan, RegisteredUser, Company, CompanyUser,
    Client, Order, StockItem,
    Invoice, InvoiceItem,
    Estimate, EstimateItem,
    PurchaseInvoice, PurchaseInvoiceItem, StockPurchaseHistory,
    CashTransaction, Loan, LoanRepayment,
    BankAccount, BankTransaction
)

app = Flask(__name__)
app.secret_key = "nexa-erp-2024-super-secret-key-change-in-production"

# ── Database Configuration ────────────────────────────────────────────────────
app.config["SQLALCHEMY_DATABASE_URI"] = (
    'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'maktroniks.db')
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

@app.before_request
def before_request():
    if db.engine.url.drivername == 'sqlite':
        db.session.execute(text('PRAGMA foreign_keys=ON'))

db.init_app(app)

# ── Create tables and seed on first startup ────────────────────────────────────
with app.app_context():
    db.drop_all()
    db.create_all()

UPLOAD_FOLDER = 'uploads/purchase_invoices'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'tiff', 'bmp'}
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

    # ── Subscription Plans
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

    # ── Registered Users
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

    # ── Companies
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

    # ── Company Users
    if CompanyUser.query.count() == 0:
        users = [
            CompanyUser(user_id="EMP001", company_id="COMP001", email="rahul@techsolutions.com",
                        password_hash=hash_password("Tech@123"), full_name="Rahul Sharma",
                        role="owner", department="Management", phone="9876543201",
                        is_active=True, created_at=date(2024, 1, 1)),
            CompanyUser(user_id="EMP002", company_id="COMP001", email="priya.mehta@techsolutions.com",
                        password_hash=hash_password("Priya@123"), full_name="Priya Mehta",
                        role="sales_manager", department="Sales", phone="9876543202",
                        is_active=True, created_at=date(2024, 1, 1)),
            CompanyUser(user_id="EMP003", company_id="COMP001", email="arjun.nair@techsolutions.com",
                        password_hash=hash_password("Arjun@123"), full_name="Arjun Nair",
                        role="accountant", department="Accounts", phone="9876543203",
                        is_active=True, created_at=date(2024, 1, 2)),
            CompanyUser(user_id="EMP101", company_id="COMP002", email="priya@globaltraders.com",
                        password_hash=hash_password("Global@123"), full_name="Priya Singh",
                        role="owner", department="Management", phone="9876543211",
                        is_active=True, created_at=date(2024, 1, 15)),
            CompanyUser(user_id="EMP102", company_id="COMP002", email="amit@globaltraders.com",
                        password_hash=hash_password("Amit@123"), full_name="Amit Kumar",
                        role="sales_executive", department="Sales", phone="9876543212",
                        is_active=True, created_at=date(2024, 1, 15)),
            CompanyUser(user_id="EMP201", company_id="COMP003", email="rahul@techsolutions.com",
                        password_hash=hash_password("Tech@123"), full_name="Rahul Sharma",
                        role="owner", department="Management", phone="9876543299",
                        is_active=True, created_at=date(2024, 3, 1)),
        ]
        db.session.add_all(users)
        db.session.commit()
        print("✔  Company users seeded.")

    # ── Sample Clients
    if Client.query.count() == 0:
        clients = [
            Client(company_id="COMP001", name="Reliance Industries", phone="9876543210",
                   pending=0, last_payment=date(2024, 1, 22), status="Paid"),
            Client(company_id="COMP001", name="Tata Consultancy", phone="9876543211",
                   pending=89500, last_payment=date(2024, 1, 5), status="Pending"),
            Client(company_id="COMP001", name="Infosys Ltd", phone="9876543212",
                   pending=86000, last_payment=date(2024, 1, 18), status="Active"),
            Client(company_id="COMP002", name="HDFC Bank", phone="9876543217",
                   pending=156000, last_payment=date(2024, 1, 1), status="Pending"),
            Client(company_id="COMP002", name="ICICI Bank", phone="9876543218",
                   pending=0, last_payment=date(2024, 1, 21), status="Paid"),
        ]
        db.session.add_all(clients)
        db.session.commit()
        print("✔  Clients seeded.")

    # ── Sample Stock Items (COMP001)
    if StockItem.query.count() == 0:
        items = [
            StockItem(company_id="COMP001", code="PROD001", name="LED TV 43 inch",
                      category="Electronics", quantity=25, unit="pcs", unit_price=35000,
                      reorder_level=10, last_updated=date(2024, 1, 20)),
            StockItem(company_id="COMP001", code="PROD002", name="Smartphone X",
                      category="Electronics", quantity=50, unit="pcs", unit_price=25000,
                      reorder_level=20, last_updated=date(2024, 1, 20)),
        ]
        db.session.add_all(items)
        db.session.commit()
        print("✔  Stock items seeded.")

    # ── Sample Orders (COMP001)
    if Order.query.count() == 0:
        c1 = Client.query.filter_by(company_id="COMP001", name="Reliance Industries").first()
        c2 = Client.query.filter_by(company_id="COMP001", name="Tata Consultancy").first()
        c3 = Client.query.filter_by(company_id="COMP001", name="Infosys Ltd").first()
        hd = Client.query.filter_by(company_id="COMP002", name="HDFC Bank").first()
        ic = Client.query.filter_by(company_id="COMP002", name="ICICI Bank").first()

        orders = [
            Order(order_id="ORD-2024-001", company_id="COMP001",
                  client_id=c1.id if c1 else None, employee_id="EMP001",
                  date=date(2024, 1, 15), amount=245000, received=245000, status="Delivered"),
            Order(order_id="ORD-2024-002", company_id="COMP001",
                  client_id=c2.id if c2 else None, employee_id="EMP002",
                  date=date(2024, 1, 17), amount=89500, received=0, status="Pending"),
            Order(order_id="ORD-2024-003", company_id="COMP001",
                  client_id=c3.id if c3 else None, employee_id="EMP001",
                  date=date(2024, 1, 18), amount=172000, received=86000, status="Processing"),
            Order(order_id="ORD-2024-101", company_id="COMP002",
                  client_id=hd.id if hd else None, employee_id="EMP101",
                  date=date(2024, 1, 20), amount=156000, received=0, status="Pending"),
            Order(order_id="ORD-2024-102", company_id="COMP002",
                  client_id=ic.id if ic else None, employee_id="EMP102",
                  date=date(2024, 1, 21), amount=89000, received=89000, status="Delivered"),
        ]
        db.session.add_all(orders)
        db.session.commit()
        print("✔  Orders seeded.")

    print("✅ Database seeding complete.")


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
        current = CompanyUser.query.filter_by(company_id=company_id, is_active=True).count()
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

        # Company employee login
        emp = CompanyUser.query.filter_by(email=email, is_active=True).first()
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
    """Add a new company for the current owner"""
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
        
        new_company = Company(
            company_id=new_company_id,
            company_name=company_name,
            owner_email=user.get("email"),
            subscription_plan=plan,
            subscription_start=date.today(),
            subscription_end=date.today() + timedelta(days=365),
            max_companies_allowed=plan_obj.max_companies,
            max_users_per_company=plan_obj.max_users,
            gst_number=gst_number,
            address=address,
            phone=phone,
            created_at=date.today(),
            is_active=True
        )
        db.session.add(new_company)
        db.session.flush()
        
        # Create company user for the owner
        emp_count = CompanyUser.query.count()
        emp_id = f"EMP{emp_count + 1:03d}"
        new_emp = CompanyUser(
            user_id=emp_id,
            company_id=new_company_id,
            email=user.get("email"),
            password_hash=hash_password(request.form.get("password", "Temp@123")),
            full_name=user.get("full_name", ""),
            role="owner",
            department="Management",
            phone=phone,
            is_active=True,
            created_at=date.today()
        )
        db.session.add(new_emp)
        db.session.commit()
        
        flash(f"Company '{company_name}' created successfully!")
        return redirect(url_for("dashboard"))
    
    return render_template("add_company.html")

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
        email             = request.form.get("email", "").strip().lower()
        password          = request.form.get("password", "")
        confirm_password  = request.form.get("confirm_password", "")
        full_name         = request.form.get("full_name", "")
        phone             = request.form.get("phone", "")
        company_name      = request.form.get("company_name", "")
        subscription_plan = request.form.get("subscription_plan", "basic")

        if RegisteredUser.query.filter_by(email=email).first():
            flash("Email already registered"); return redirect(url_for("register"))
        if password != confirm_password:
            flash("Passwords do not match"); return redirect(url_for("register"))
        if len(password) < 6:
            flash("Password must be at least 6 characters"); return redirect(url_for("register"))

        plan_obj = SubscriptionPlan.query.get(subscription_plan) or SubscriptionPlan.query.get("basic")
        reg_count = RegisteredUser.query.count()
        user_id   = f"USR{reg_count + 1:03d}"

        new_user = RegisteredUser(
            user_id=user_id, email=email, password_hash=hash_password(password),
            full_name=full_name, phone=phone, role="owner",
            subscription_plan=plan_obj.id, created_at=date.today(), is_active=True,
        )
        db.session.add(new_user)
        db.session.flush()

        comp_count  = Company.query.count()
        company_id  = f"COMP{comp_count + 1:03d}"
        end_days    = 730 if plan_obj.id == "custom" else 365
        new_company = Company(
            company_id=company_id, company_name=company_name,
            owner_email=email, subscription_plan=plan_obj.id,
            subscription_start=date.today(),
            subscription_end=date.today() + timedelta(days=end_days),
            max_companies_allowed=plan_obj.max_companies,
            max_users_per_company=plan_obj.max_users,
            gst_number=request.form.get("gst_number", ""),
            address=request.form.get("address", ""),
            phone=phone, created_at=date.today(), is_active=True,
        )
        db.session.add(new_company)
        db.session.flush()

        emp_count = CompanyUser.query.count()
        emp_id    = f"EMP{emp_count + 1:03d}"
        new_emp   = CompanyUser(
            user_id=emp_id, company_id=company_id, email=email,
            password_hash=hash_password(password), full_name=full_name,
            role="owner", department="Management", phone=phone,
            is_active=True, created_at=date.today(),
        )
        db.session.add(new_emp)
        db.session.commit()

        flash("Registration successful! Please login.")
        return redirect(url_for("login"))

    return render_template("register.html", plans=get_all_plans())


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))







# ─────────────────────────────────────────────────────────────────────────────
# ── Dashboard ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
"""@app.route("/dashboard")
@login_required
def dashboard():
    company_id = get_current_company()
    company    = get_company_by_id(company_id)

    orders    = Order.query.filter_by(company_id=company_id).all()
    clients   = Client.query.filter_by(company_id=company_id).all()
    employees = CompanyUser.query.filter_by(company_id=company_id, is_active=True).all()
    invoices  = Invoice.query.filter_by(company_id=company_id).all()
    purchases = PurchaseInvoice.query.filter_by(company_id=company_id).all()
    stock     = StockItem.query.filter_by(company_id=company_id).all()

    total_revenue   = sum(o.amount    for o in orders)
    total_received  = sum(o.received  for o in orders)
    pending_orders  = [o for o in orders if o.status == "Pending"]

    # Invoice billing totals
    total_billing   = sum(i.grand_total  for i in invoices)
    total_inv_paid  = sum((i.grand_total - getattr(i, "balance", 0)) for i in invoices)
    total_inv_due   = sum(getattr(i, "balance", 0) for i in invoices)

    # Purchase totals
    total_purchases = sum(p.grand_total  for p in purchases)
    total_pur_paid  = sum(p.paid_amount  for p in purchases)
    total_pur_due   = sum(p.balance      for p in purchases)

    # Stock
    low_stock       = [s for s in stock if s.quantity <= s.reorder_level]
    total_stock_val = sum((s.purchase_rate or 0) * s.quantity for s in stock)

    stats = {
        # Orders
        "total_orders":    len(orders),
        "total_revenue":   total_revenue,
        "total_received":  total_received,
        "pending_amount":  total_revenue - total_received,
        "pending_orders":  len(pending_orders),
        # Clients / Employees
        "total_clients":   len(clients),
        "total_employees": len(employees),
        # Invoices / Billing
        "total_billing":   total_billing,
        "total_inv_paid":  total_inv_paid,
        "total_inv_due":   total_inv_due,
        "total_invoices":  len(invoices),
        # Purchases
        "total_purchases": total_purchases,
        "total_pur_paid":  total_pur_paid,
        "total_pur_due":   total_pur_due,
        "total_purchase_count": len(purchases),
        # Stock
        "total_stock_items": len(stock),
        "low_stock_count":   len(low_stock),
        "total_stock_value": total_stock_val,
        # Estimates
        "total_estimates": Estimate.query.filter_by(company_id=company_id).count(),
    }

    recent_orders_raw    = sorted(orders,    key=lambda o: o.date, reverse=True)[:5]
    recent_invoices_raw  = sorted(invoices,  key=lambda i: i.date, reverse=True)[:5]
    recent_purchases_raw = sorted(purchases, key=lambda p: p.date, reverse=True)[:5]
    top_clients          = sorted(clients,   key=lambda c: c.pending, reverse=True)[:5]

    # Serialize invoices → dicts so template can use .total, .paid, .balance, .status
    recent_invoices = []
    for inv in recent_invoices_raw:
        paid    = getattr(inv, "paid_amount", 0) or 0
        bal     = getattr(inv, "balance",     0) or 0
        total   = inv.grand_total or 0
        st_raw  = (inv.status or "").lower()
        status  = "paid" if st_raw == "paid" else ("partial" if st_raw == "partial" else "pending")
        cname   = inv.client_obj.name if inv.client_obj else (inv.contact_person or "—")
        recent_invoices.append({
            "id":            inv.invoice_id,
            "customer_name": cname,
            "date":          inv.date.strftime("%d %b %Y") if inv.date else "—",
            "total":         total,
            "paid":          paid,
            "balance":       bal,
            "status":        status,
        })

    # Serialize orders → dicts
    recent_orders = []
    for o in recent_orders_raw:
        cname = o.client_obj.name if hasattr(o, "client_obj") and o.client_obj else (getattr(o, "contact_person", "") or "—")
        recent_orders.append({
            "id":     o.order_id if hasattr(o, "order_id") else str(o.id),
            "client": cname,
            "date":   o.date.strftime("%d %b %Y") if o.date else "—",
            "amount": getattr(o, "grand_total", 0) or 0,
            "status": o.status or "Pending",
        })

    # Serialize recent estimates → dicts
    recent_estimates_raw = (
        Estimate.query.filter_by(company_id=company_id)
        .order_by(Estimate.date.desc()).limit(5).all()
    )
    recent_estimates = []
    for e in recent_estimates_raw:
        meta = {}
        if e.terms:
            try:
                meta = json.loads(e.terms)
            except (ValueError, TypeError):
                pass
        cname = e.client_obj.name if e.client_obj else (e.contact_person or "—")
        recent_estimates.append({
            "id":          e.estimate_id,
            "company":     cname,
            "date":        e.date.strftime("%d %b %Y") if e.date else "—",
            "valid_until": e.valid_until.strftime("%d %b %Y") if e.valid_until else "—",
            "total":       e.grand_total or 0,
            "status":      e.status or "Draft",
            "docket_no":   meta.get("docket_no", ""),
        })

    # Add missing stats fields dashboard.html expects
    paid_inv_count    = sum(1 for i in invoices if (i.status or "").lower() == "paid")
    pending_inv_count = sum(1 for i in invoices if (i.status or "").lower() not in ("paid",))
    approved_est      = Estimate.query.filter_by(company_id=company_id, status="Approved").count()
    stats["paid_invoices"]      = paid_inv_count
    stats["pending_invoices"]   = pending_inv_count
    stats["approved_estimates"] = approved_est

    user_companies = []
    user = get_current_user()
    if user.get("role") == "owner":
        user_companies = get_owner_companies(user.get("email"))

    return render_template("dashboard.html",
                           company=company,
                           stats=stats,
                           recent_orders=recent_orders,
                           recent_invoices=recent_invoices,
                           recent_estimates=recent_estimates,
                           recent_purchases=recent_purchases_raw,
                           top_clients=top_clients,
                           low_stock=low_stock,
                           user_companies=user_companies,
                           user=user)"""

@app.route("/dashboard")
@login_required
def dashboard():
    company_id = get_current_company()
    company    = get_company_by_id(company_id)

    # Get date filters from request
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    
    # Set default dates (current month)
    if not from_date_str:
        from_date = date.today().replace(day=1)
    else:
        from_date = date.fromisoformat(from_date_str)
    
    if not to_date_str:
        to_date = date.today()
    else:
        to_date = date.fromisoformat(to_date_str)

    # ─────────────────────────────────────────────────────────────────────────
    # KPI Calculations
    # ─────────────────────────────────────────────────────────────────────────
    
    # Cash in Hand
    cash_transactions = CashTransaction.query.filter_by(company_id=company_id).all()
    cash_balance = sum(t.amount for t in cash_transactions if t.type == 'income') - \
                   sum(t.amount for t in cash_transactions if t.type == 'expense')
    
    # Bank Balance
    bank_accounts = BankAccount.query.filter_by(company_id=company_id, status='Active').all()
    bank_balance = sum(acc.balance for acc in bank_accounts)
    
    # Filtered Sales Invoices (Revenue)
    sales_invoices = Invoice.query.filter(
        Invoice.company_id == company_id,
        Invoice.date >= from_date,
        Invoice.date <= to_date
    ).all()
    total_revenue = sum(float(inv.grand_total or 0) for inv in sales_invoices)
    
    # Filtered Purchase Invoices
    purchase_invoices = PurchaseInvoice.query.filter(
        PurchaseInvoice.company_id == company_id,
        PurchaseInvoice.date >= from_date,
        PurchaseInvoice.date <= to_date
    ).all()
    total_purchases = sum(float(pur.grand_total or 0) for pur in purchase_invoices)
    
    # Gross Profit
    profit = total_revenue - total_purchases
    
    # Pending Amount (from unpaid invoices)
    all_invoices = Invoice.query.filter_by(company_id=company_id).all()
    # FIX: Convert Decimal to float
    pending_amount = sum(float(getattr(inv, 'balance', 0) or 0) for inv in all_invoices)
    
    # Cash flow for the period
    period_cash_income = CashTransaction.query.filter(
        CashTransaction.company_id == company_id,
        CashTransaction.type == 'income',
        CashTransaction.date >= from_date,
        CashTransaction.date <= to_date
    ).all()
    period_cash_expense = CashTransaction.query.filter(
        CashTransaction.company_id == company_id,
        CashTransaction.type == 'expense',
        CashTransaction.date >= from_date,
        CashTransaction.date <= to_date
    ).all()
    cash_inflow_period = sum(t.amount for t in period_cash_income)
    cash_outflow_period = sum(t.amount for t in period_cash_expense)
    cash_net_period = cash_inflow_period - cash_outflow_period
    
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
    
    # ─────────────────────────────────────────────────────────────────────────
    # Chart Data: Revenue vs Purchase (Last 6 months)
    # ─────────────────────────────────────────────────────────────────────────
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
        
        # Revenue for month
        month_revenue = sum(
            float(inv.grand_total or 0) for inv in Invoice.query.filter(
                Invoice.company_id == company_id,
                Invoice.date >= month_start,
                Invoice.date <= month_end
            ).all()
        )
        revenue_data.append(month_revenue / 100000)  # Convert to Lakhs
        
        # Purchases for month
        month_purchases = sum(
            float(pur.grand_total or 0) for pur in PurchaseInvoice.query.filter(
                PurchaseInvoice.company_id == company_id,
                PurchaseInvoice.date >= month_start,
                PurchaseInvoice.date <= month_end
            ).all()
        )
        purchase_data.append(month_purchases / 100000)
        
        # Profit trend (last 6 months)
        if i <= 5:
            profit_labels.append(month_label)
            profit_trend.append((month_revenue - month_purchases) / 1000)  # In thousands
    
    # ─────────────────────────────────────────────────────────────────────────
    # Top Clients Data
    # ─────────────────────────────────────────────────────────────────────────
    clients = Client.query.filter_by(company_id=company_id).all()
    top_clients_data = []
    for client in clients[:10]:
        client_invoices = Invoice.query.filter_by(company_id=company_id, client_id=client.id).all()
        total_billed = sum(float(inv.grand_total or 0) for inv in client_invoices)
        pending = sum(float(getattr(inv, 'balance', 0) or 0) for inv in client_invoices)
        top_clients_data.append({
            "name": client.name,
            "total_billed": total_billed,
            "pending": pending,
            "status": client.status or "Active"
        })
    top_clients_data.sort(key=lambda x: x["total_billed"], reverse=True)
    top_clients_data = top_clients_data[:5]
    
    # ─────────────────────────────────────────────────────────────────────────
    # Recent Invoices (last 10)
    # ─────────────────────────────────────────────────────────────────────────
    recent_invoices_raw = Invoice.query.filter_by(company_id=company_id).order_by(Invoice.date.desc()).limit(10).all()
    recent_invoices_data = []
    for inv in recent_invoices_raw:
        client_name = inv.client_obj.name if inv.client_obj else (inv.contact_person or "—")
        total = float(inv.grand_total or 0)
        balance = float(getattr(inv, 'balance', 0) or 0)
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
    
    # ─────────────────────────────────────────────────────────────────────────
    # Low Stock Items
    # ─────────────────────────────────────────────────────────────────────────
    stock_items = StockItem.query.filter_by(company_id=company_id).all()
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
    
    # ─────────────────────────────────────────────────────────────────────────
    # Get employee count
    # ─────────────────────────────────────────────────────────────────────────
    employees = CompanyUser.query.filter_by(company_id=company_id, is_active=True).all()
    
    # ─────────────────────────────────────────────────────────────────────────
    # Orders data (for any additional metrics)
    # ─────────────────────────────────────────────────────────────────────────
    orders = Order.query.filter_by(company_id=company_id).all()
    clients_list = Client.query.filter_by(company_id=company_id).all()
    
    # Invoice billing totals - FIX Decimal conversion
    invoices = Invoice.query.filter_by(company_id=company_id).all()
    total_billing = sum(float(i.grand_total or 0) for i in invoices)
    total_inv_paid = sum(float(i.grand_total or 0) - float(getattr(i, "balance", 0) or 0) for i in invoices)
    total_inv_due = sum(float(getattr(i, "balance", 0) or 0) for i in invoices)
    
    stats = {
        "total_orders": len(orders),
        "total_revenue": total_revenue,
        "total_received": sum(o.received for o in orders),
        "pending_amount": pending_amount,
        "pending_orders": len([o for o in orders if o.status == "Pending"]),
        "total_clients": len(clients_list),
        "total_employees": len(employees),
        "total_billing": total_billing,
        "total_inv_paid": total_inv_paid,
        "total_inv_due": total_inv_due,
        "total_invoices": len(invoices),
        "paid_invoices": sum(1 for i in invoices if (i.status or "").lower() == "paid"),
        "pending_invoices": sum(1 for i in invoices if (i.status or "").lower() not in ("paid",)),
    }
    
    user_companies = []
    user = get_current_user()
    if user.get("role") == "owner":
        user_companies = get_owner_companies(user.get("email"))
    
    # Recent orders for quick view
    recent_orders_raw = sorted(orders, key=lambda o: o.date, reverse=True)[:5]
    recent_orders = []
    for o in recent_orders_raw:
        cname = o.client_obj.name if hasattr(o, "client_obj") and o.client_obj else (getattr(o, "contact_person", "") or "—")
        recent_orders.append({
            "id": o.order_id if hasattr(o, "order_id") else str(o.id),
            "client": cname,
            "date": o.date.strftime("%d %b %Y") if o.date else "—",
            "amount": float(getattr(o, "grand_total", 0) or 0),
            "status": o.status or "Pending",
        })
    
    # Recent estimates
    recent_estimates_raw = Estimate.query.filter_by(company_id=company_id).order_by(Estimate.date.desc()).limit(5).all()
    recent_estimates = []
    for e in recent_estimates_raw:
        meta = {}
        if e.terms:
            try:
                meta = json.loads(e.terms)
            except (ValueError, TypeError):
                pass
        cname = e.client_obj.name if e.client_obj else (e.contact_person or "—")
        recent_estimates.append({
            "id": e.estimate_id,
            "company": cname,
            "date": e.date.strftime("%d %b %Y") if e.date else "—",
            "valid_until": e.valid_until.strftime("%d %b %Y") if e.valid_until else "—",
            "total": float(e.grand_total or 0),
            "status": e.status or "Draft",
            "docket_no": meta.get("docket_no", ""),
        })
    
    stats["approved_estimates"] = Estimate.query.filter_by(company_id=company_id, status="Approved").count()

    return render_template("dashboard.html",
                           company=company,
                           stats=stats,
                           kpi=kpi,
                           from_date=from_date.strftime('%Y-%m-%d'),
                           to_date=to_date.strftime('%Y-%m-%d'),
                           chart_labels=chart_labels,
                           revenue_data=revenue_data,
                           purchase_data=purchase_data,
                           profit_labels=profit_labels,
                           profit_trend=profit_trend,
                           top_clients_data=top_clients_data,
                           recent_invoices_data=recent_invoices_data,
                           low_stock_items=low_stock_items,
                           cash_inflow_period=cash_inflow_period,
                           cash_outflow_period=cash_outflow_period,
                           cash_net_period=cash_net_period,
                           recent_orders=recent_orders,
                           recent_estimates=recent_estimates,
                           user_companies=user_companies,
                           user=user)

@app.route("/api/dashboard-data")
@login_required
def api_dashboard_data():
    """API endpoint for dashboard data with date filters"""
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
    
    # Cash in Hand
    cash_transactions = CashTransaction.query.filter_by(company_id=company_id).all()
    cash_balance = sum(t.amount for t in cash_transactions if t.type == 'income') - \
                   sum(t.amount for t in cash_transactions if t.type == 'expense')
    
    # Bank Balance
    bank_accounts = BankAccount.query.filter_by(company_id=company_id, status='Active').all()
    bank_balance = sum(acc.balance for acc in bank_accounts)
    
    # Filtered Sales Invoices
    sales_invoices = Invoice.query.filter(
        Invoice.company_id == company_id,
        Invoice.date >= from_date,
        Invoice.date <= to_date
    ).all()
    total_revenue = sum(inv.grand_total or 0 for inv in sales_invoices)
    
    # Filtered Purchase Invoices
    purchase_invoices = PurchaseInvoice.query.filter(
        PurchaseInvoice.company_id == company_id,
        PurchaseInvoice.date >= from_date,
        PurchaseInvoice.date <= to_date
    ).all()
    total_purchases = sum(pur.grand_total or 0 for pur in purchase_invoices)
    
    profit = total_revenue - total_purchases
    
    all_invoices = Invoice.query.filter_by(company_id=company_id).all()
    pending_amount = sum(getattr(inv, 'balance', 0) or 0 for inv in all_invoices)
    
    period_cash_income = CashTransaction.query.filter(
        CashTransaction.company_id == company_id,
        CashTransaction.type == 'income',
        CashTransaction.date >= from_date,
        CashTransaction.date <= to_date
    ).all()
    period_cash_expense = CashTransaction.query.filter(
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
            inv.grand_total or 0 for inv in Invoice.query.filter(
                Invoice.company_id == company_id,
                Invoice.date >= month_start,
                Invoice.date <= month_end
            ).all()
        )
        revenue_data.append(month_revenue / 100000)
        
        month_purchases = sum(
            pur.grand_total or 0 for pur in PurchaseInvoice.query.filter(
                PurchaseInvoice.company_id == company_id,
                PurchaseInvoice.date >= month_start,
                PurchaseInvoice.date <= month_end
            ).all()
        )
        purchase_data.append(month_purchases / 100000)
        
        if i <= 5:
            profit_labels.append(month_label)
            profit_trend.append((month_revenue - month_purchases) / 1000)
    
    # Top clients
    clients = Client.query.filter_by(company_id=company_id).all()
    top_clients_data = []
    for client in clients[:10]:
        client_invoices = Invoice.query.filter_by(company_id=company_id, client_id=client.id).all()
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
    recent_invoices_raw = Invoice.query.filter_by(company_id=company_id).order_by(Invoice.date.desc()).limit(10).all()
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
    stock_items = StockItem.query.filter_by(company_id=company_id).all()
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
            "profit": profit,
            "pending_amount": pending_amount,
            "cash_inflow_period": cash_inflow_period,
            "cash_outflow_period": cash_outflow_period,
            "cash_net_period": cash_inflow_period - cash_outflow_period,
        },
        "chart_labels": chart_labels,
        "revenue_data": revenue_data,
        "purchase_data": purchase_data,
        "profit_labels": profit_labels,
        "profit_trend": profit_trend,
        "top_clients": top_clients_data,
        "recent_invoices": recent_invoices_data,
        "low_stock": low_stock_items,
    })

# ─────────────────────────────────────────────────────────────────────────────
# ── Orders ────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/orders")
@login_required
def order_list():
    company_id    = get_current_company()
    filter_status = request.args.get("status", "All")
    query         = Order.query.filter_by(company_id=company_id)
    if filter_status != "All":
        query = query.filter_by(status=filter_status)
    orders  = query.order_by(Order.date.desc()).all()
    clients = Client.query.filter_by(company_id=company_id).all()
    return render_template("orders.html", orders=orders, clients=clients,
                           current_status=filter_status)


@app.route("/orders/add", methods=["GET", "POST"])
@login_required
def order_add():
    company_id = get_current_company()
    clients    = Client.query.filter_by(company_id=company_id).all()

    if request.method == "POST":
        client_id   = request.form.get("client_id")
        amount      = float(request.form.get("amount", 0))
        received    = float(request.form.get("received", 0))
        status      = request.form.get("status", "Pending")
        order_date  = request.form.get("order_date") or str(date.today())
        ord_count   = Order.query.count()
        new_order   = Order(
            order_id=f"ORD-{datetime.now().strftime('%Y%m%d')}-{ord_count+1:03d}",
            company_id=company_id,
            client_id=int(client_id) if client_id else None,
            employee_id=get_current_user().get("user_id"),
            date=date.fromisoformat(order_date),
            amount=amount, received=received, status=status,
        )
        db.session.add(new_order)
        db.session.commit()
        flash("Order created successfully!")
        return redirect(url_for("order_list"))

    return render_template("order_form.html", clients=clients)


@app.route("/orders/edit/<int:order_pk>", methods=["GET", "POST"])
@login_required
def order_edit(order_pk):
    company_id = get_current_company()
    order      = Order.query.filter_by(id=order_pk, company_id=company_id).first_or_404()
    clients    = Client.query.filter_by(company_id=company_id).all()

    if request.method == "POST":
        order.client_id = int(request.form.get("client_id")) if request.form.get("client_id") else None
        order.amount    = float(request.form.get("amount", 0))
        order.received  = float(request.form.get("received", 0))
        order.status    = request.form.get("status", "Pending")
        db.session.commit()
        flash("Order updated!")
        return redirect(url_for("order_list"))

    return render_template("order_form.html", order=order, clients=clients)


@app.route("/orders/delete/<int:order_pk>", methods=["POST"])
@login_required
def order_delete(order_pk):
    company_id = get_current_company()
    order      = Order.query.filter_by(id=order_pk, company_id=company_id).first_or_404()
    db.session.delete(order)
    db.session.commit()
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
    company_id    = get_current_company()
    filter_status = request.args.get("status", "All")

    query = Client.query.filter_by(company_id=company_id)
    if filter_status != "All":
        query = query.filter_by(status=filter_status)

    clients = [_normalize_client(c) for c in query.all()]
    return render_template("clients.html", clients=clients, current_status=filter_status)


# /clients/new  ── template links here for new client
@app.route("/clients/new", methods=["GET", "POST"])
@login_required
def client_new():
    company_id = get_current_company()
    if request.method == "POST":
        f = request.form

        # GST uniqueness check (per company)
        gst = f.get("gst_number", "").strip().upper()
        if gst:
            existing_gst = Client.query.filter_by(
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
        db.session.add(new_client)
        db.session.commit()
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
    company_id = get_current_company()
    c = Client.query.filter_by(id=client_pk, company_id=company_id).first_or_404()
    client = _normalize_client(c)
    invoices = Invoice.query.filter_by(company_id=company_id, client_id=c.id).order_by(Invoice.date.desc()).all()
    orders   = Order.query.filter_by(company_id=company_id, client_id=c.id).order_by(Order.date.desc()).all()
    return render_template("client_detail.html", client=client, invoices=invoices, orders=orders)


# /clients/<id>/edit
@app.route("/clients/<int:client_pk>/edit", methods=["GET", "POST"])
@login_required
def client_edit(client_pk):
    company_id = get_current_company()
    c          = Client.query.filter_by(id=client_pk, company_id=company_id).first_or_404()
    if request.method == "POST":
        f   = request.form
        gst = f.get("gst_number", "").strip().upper()

        # GST uniqueness: check no OTHER client has the same GST
        if gst:
            existing_gst = Client.query.filter(
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
        db.session.commit()
        flash(f"Client '{c.name}' updated successfully!")
        return redirect(url_for("client_list"))
    return render_template("client_form.html", client=_normalize_client(c), form_data={})


# /clients/<id>/delete  ── template uses GET link with confirm dialog
@app.route("/clients/<int:client_pk>/delete", methods=["GET", "POST"])
@login_required
def client_delete(client_pk):
    company_id = get_current_company()
    c          = Client.query.filter_by(id=client_pk, company_id=company_id).first_or_404()
    db.session.delete(c)
    db.session.commit()
    flash("Client deleted.")
    return redirect(url_for("client_list"))


# ─────────────────────────────────────────────────────────────────────────────
# ── Stock / Inventory ─────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/inventory")
@login_required
def inventory_list():
    company_id  = get_current_company()
    stock_items = StockItem.query.filter_by(company_id=company_id).all()

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
                           stock_summary=stock_summary)


# ── Stock JSON API (used by inventory.html JS modals) ────────────────────────
@app.route("/stock/item/<code>")
@login_required
def stock_item_get(code):
    company_id = get_current_company()
    item = StockItem.query.filter_by(company_id=company_id, code=code.upper()).first_or_404()
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
    
    company_id = get_current_company()
    items = StockItem.query.filter_by(company_id=company_id).order_by(StockItem.name).all()
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
    company_id = get_current_company()
    data       = request.get_json(force=True)

    code = data.get("code", "").strip().upper()
    item = StockItem.query.filter_by(company_id=company_id, code=code).first() if code else None

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
            count = StockItem.query.filter_by(company_id=company_id).count()
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
        db.session.add(item)

    db.session.commit()
    return jsonify({"success": True, "code": item.code})


@app.route("/stock/adjust", methods=["POST"])
@login_required
def stock_adjust():
    """Quick quantity adjustment from the Adj button in the table."""
    company_id = get_current_company()
    data       = request.get_json(force=True)
    code       = data.get("code", "").strip().upper()
    item       = StockItem.query.filter_by(company_id=company_id, code=code).first_or_404()
    item.quantity     = float(data.get("quantity", item.quantity))
    item.last_updated = date.today()
    db.session.commit()
    return jsonify({"success": True})


@app.route("/stock/movements/<code>")
@login_required
def stock_movements(code):
    """Return full movement history for a stock item (purchases IN, invoices OUT)."""
    company_id = get_current_company()
    item = StockItem.query.filter_by(
        company_id=company_id, code=code.upper()
    ).first_or_404()

    history = (
        StockPurchaseHistory.query
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
            inv = PurchaseInvoice.query.get(h.purchase_invoice_id)
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
        db.session.add(item)
        db.session.commit()
        flash("Stock item added!")
        return redirect(url_for("inventory_list"))
    return render_template("inventory_form.html")


@app.route("/inventory/edit/<int:item_pk>", methods=["GET", "POST"])
@login_required
def inventory_edit(item_pk):
    company_id = get_current_company()
    item       = StockItem.query.filter_by(id=item_pk, company_id=company_id).first_or_404()
    if request.method == "POST":
        item.name          = request.form.get("name", item.name)
        item.category      = request.form.get("category", item.category)
        item.quantity      = float(request.form.get("quantity", item.quantity))
        item.unit          = request.form.get("unit", item.unit)
        item.unit_price    = float(request.form.get("unit_price", item.unit_price))
        item.reorder_level = float(request.form.get("reorder_level", item.reorder_level))
        item.hsn           = request.form.get("hsn", item.hsn)
        item.last_updated  = date.today()
        db.session.commit()
        flash("Stock item updated!")
        return redirect(url_for("inventory_list"))
    return render_template("inventory_form.html", item=item)


@app.route("/inventory/delete/<int:item_pk>", methods=["POST"])
@login_required
def inventory_delete(item_pk):
    company_id = get_current_company()
    item       = StockItem.query.filter_by(id=item_pk, company_id=company_id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash("Stock item deleted.")
    return redirect(url_for("inventory_list"))

# ── Purchase Invoice Routes ─────────────────────────────────────────────────────────

@app.route("/purchase/list")
@login_required
def purchase_invoice_list():
    company_id = get_current_company()
    invoices = PurchaseInvoice.query.filter_by(company_id=company_id).order_by(PurchaseInvoice.date.desc()).all()
    total_amount = sum(p.grand_total for p in invoices)
    total_paid = sum(p.paid_amount for p in invoices)
    total_due = sum(p.balance for p in invoices)
    
    return render_template("purchases.html",
        purchases=invoices,
        total_amount=total_amount,
        total_paid=total_paid,
        total_due=total_due
    )

"""@app.route("/purchase/new", methods=["GET", "POST"])
@login_required
def purchase_invoice_new():
    company_id = get_current_company()
    suppliers = Client.query.filter(
        Client.company_id == company_id,
        db.or_(Client.client_type == "Supplier", Client.client_type == "Both")
    ).all()
    
    if request.method == "POST":
        supplier_id = request.form.get("supplier_id")
        supplier_name = request.form.get("supplier_name", "").strip()

        if not supplier_id and supplier_name:
            existing = Client.query.filter_by(
                company_id=company_id, name=supplier_name
            ).first()
            if existing:
                supplier_id = existing.id
            else:
                new_supplier = Client(
                    company_id=company_id,
                    name=supplier_name,
                    client_type="Supplier",
                    gst_number=request.form.get("supplier_gst", "").strip() or None,
                    status="Active",
                    created_at=date.today()
                )
                db.session.add(new_supplier)
                db.session.flush()
                supplier_id = new_supplier.id
        invoice_number = request.form.get("invoice_number", "")
        invoice_date = request.form.get("invoice_date") or str(date.today())
        due_date = request.form.get("due_date")
        payment_terms = request.form.get("payment_terms", "")
        notes = request.form.get("notes", "")
        
        descriptions = request.form.getlist("item_description[]")
        quantities = request.form.getlist("item_quantity[]")
        units = request.form.getlist("item_unit[]")
        rates = request.form.getlist("item_rate[]")
        gst_percents = request.form.getlist("item_gst[]")
        
        subtotal = 0
        tax_total = 0
        items_data = []
        
        for i in range(len(descriptions)):
            if descriptions[i] and descriptions[i].strip():
                qty = float(quantities[i]) if quantities[i] else 0
                rate = float(rates[i]) if rates[i] else 0
                gst = float(gst_percents[i]) if gst_percents[i] else 0
                
                line_total = qty * rate
                tax_amount = line_total * (gst / 100)
                
                subtotal += line_total
                tax_total += tax_amount
                
                items_data.append({
                    "description": descriptions[i],
                    "quantity": qty,
                    "unit": units[i] if units[i] else "pcs",
                    "rate": rate,
                    "gst": gst,
                    "total": line_total + tax_amount
                })
        
        grand_total = subtotal + tax_total
        
        inv_count = PurchaseInvoice.query.count()
        invoice_id = f"PURCHASE-INV-{datetime.now().strftime('%Y%m%d')}-{inv_count+1:03d}"
        
        purchase_inv = PurchaseInvoice(
            invoice_id=invoice_id,
            company_id=company_id,
            supplier_id=int(supplier_id) if supplier_id else None,
            invoice_number=invoice_number,
            date=date.fromisoformat(invoice_date),
            due_date=date.fromisoformat(due_date) if due_date else None,
            subtotal=subtotal,
            tax_amount=tax_total,
            grand_total=grand_total,
            paid_amount=0,
            balance=grand_total,
            status="Pending",
            payment_terms=payment_terms,
            notes=notes,
            created_at=datetime.utcnow()
        )
        db.session.add(purchase_inv)
        db.session.flush()
        
        for item in items_data:
            stock_item = StockItem.query.filter_by(
                company_id=company_id,
                name=item["description"]
            ).first()
            
            if not stock_item:
                stock_count = StockItem.query.filter_by(company_id=company_id).count()
                stock_item = StockItem(
                    company_id=company_id,
                    code=f"AUTO-{stock_count+1:03d}",
                    name=item["description"],
                    category="Purchase",
                    quantity=0,
                    unit=item["unit"],
                    unit_price=0,
                    purchase_rate=item["rate"],
                    last_purchase_rate=item["rate"],
                    gst_percent=item["gst"],
                    last_updated=date.today()
                )
                db.session.add(stock_item)
                db.session.flush()
            
            stock_item.quantity += item["quantity"]
            stock_item.last_purchase_rate = item["rate"]
            stock_item.gst_percent = item["gst"]
            stock_item.last_updated = date.today()
            
            purchase_history = StockPurchaseHistory(
                stock_item_id=stock_item.id,
                purchase_invoice_id=purchase_inv.id,
                quantity=item["quantity"],
                purchase_rate=item["rate"],
                gst_percent=item["gst"],
                purchase_date=date.fromisoformat(invoice_date)
            )
            db.session.add(purchase_history)
            
            inv_item = PurchaseInvoiceItem(
                purchase_invoice_id=purchase_inv.id,
                stock_item_id=stock_item.id,
                description=item["description"],
                quantity=item["quantity"],
                unit=item["unit"],
                purchase_rate=item["rate"],
                gst_percent=item["gst"],
                total_amount=item["total"]
            )
            db.session.add(inv_item)
            
            supplier = Client.query.get(supplier_id)
            if supplier:
                supplier.pending += item["total"]
                supplier.last_payment = date.today()
        
        db.session.commit()
        
        # Handle file upload for storage
        if 'invoice_file' in request.files:
            file = request.files['invoice_file']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"{invoice_id}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                purchase_inv.file_path = filepath
                db.session.commit()
        
        flash(f"Purchase invoice {invoice_id} created successfully!")
        return redirect(url_for("purchase_invoice_list"))
    
    return render_template("purchase_form.html", suppliers=suppliers, today=str(date.today()))"""

@app.route("/purchase/new", methods=["GET", "POST"])
@login_required
def purchase_invoice_new():
    company_id = get_current_company()
    suppliers = Client.query.filter(
        Client.company_id == company_id,
        db.or_(Client.client_type == "Supplier", Client.client_type == "Both")
    ).all()

    if request.method == "POST":
        supplier_id   = request.form.get("supplier_id")
        supplier_name = request.form.get("supplier_name", "").strip()
        supplier_gst  = request.form.get("supplier_gst", "").strip()

        # Auto-create supplier if not selected from dropdown
        if not supplier_id and supplier_name:
            existing = Client.query.filter_by(
                company_id=company_id, name=supplier_name
            ).first()
            if existing:
                supplier_id = existing.id
            else:
                new_supplier = Client(
                    company_id=company_id,
                    name=supplier_name,
                    client_type="Supplier",
                    gst_number=supplier_gst or None,
                    status="Active",
                    created_at=date.today()
                )
                db.session.add(new_supplier)
                db.session.flush()
                supplier_id = new_supplier.id
        elif supplier_id and supplier_gst:
            # Update GST on existing supplier if provided
            sup = Client.query.get(int(supplier_id))
            if sup and not sup.gst_number:
                sup.gst_number = supplier_gst

        invoice_number = request.form.get("invoice_number", "")
        invoice_date   = request.form.get("invoice_date") or str(date.today())
        due_date       = request.form.get("due_date")
        payment_terms  = request.form.get("payment_terms", "")
        notes          = request.form.get("notes", "")

        # Item arrays from the form
        descriptions = request.form.getlist("item_description[]")
        quantities   = request.form.getlist("item_quantity[]")
        units        = request.form.getlist("item_unit[]")
        rates        = request.form.getlist("item_rate[]")
        gst_percents = request.form.getlist("item_gst[]")
        stock_ids    = request.form.getlist("item_stock_id[]")   # NEW: pre-linked stock items

        subtotal   = 0
        tax_total  = 0
        items_data = []

        for i in range(len(descriptions)):
            if descriptions[i] and descriptions[i].strip():
                qty  = float(quantities[i])  if quantities[i]  else 0
                rate = float(rates[i])       if rates[i]       else 0
                gst  = float(gst_percents[i])if gst_percents[i]else 0

                line_total = qty * rate
                tax_amount = line_total * (gst / 100)

                subtotal  += line_total
                tax_total += tax_amount

                items_data.append({
                    "description": descriptions[i],
                    "quantity":    qty,
                    "unit":        units[i] if units[i] else "pcs",
                    "rate":        rate,
                    "gst":         gst,
                    "total":       line_total + tax_amount,
                    "stock_id":    int(stock_ids[i]) if (i < len(stock_ids) and stock_ids[i]) else None,
                })

        grand_total = subtotal + tax_total

        inv_count  = PurchaseInvoice.query.count()
        invoice_id = f"PURCHASE-INV-{datetime.now().strftime('%Y%m%d')}-{inv_count+1:03d}"

        purchase_inv = PurchaseInvoice(
            invoice_id=invoice_id,
            company_id=company_id,
            supplier_id=int(supplier_id) if supplier_id else None,
            invoice_number=invoice_number,
            date=date.fromisoformat(invoice_date),
            due_date=date.fromisoformat(due_date) if due_date else None,
            subtotal=subtotal,
            tax_amount=tax_total,
            grand_total=grand_total,
            paid_amount=0,
            balance=grand_total,
            status="Pending",
            payment_terms=payment_terms,
            notes=notes,
            created_at=datetime.utcnow()
        )
        db.session.add(purchase_inv)
        db.session.flush()

        for item in items_data:
            # Try to use the pre-linked stock item first
            stock_item = None
            if item["stock_id"]:
                stock_item = StockItem.query.filter_by(
                    id=item["stock_id"], company_id=company_id
                ).first()

            # Fallback: match by name
            if not stock_item:
                stock_item = StockItem.query.filter_by(
                    company_id=company_id, name=item["description"]
                ).first()

            # Still not found: auto-create
            if not stock_item:
                stock_count = StockItem.query.filter_by(company_id=company_id).count()
                stock_item = StockItem(
                    company_id=company_id,
                    code=f"AUTO-{stock_count+1:03d}",
                    name=item["description"],
                    category="Purchase",
                    quantity=0,
                    unit=item["unit"],
                    unit_price=0,
                    purchase_rate=item["rate"],
                    last_purchase_rate=item["rate"],
                    gst_percent=item["gst"],
                    last_updated=date.today()
                )
                db.session.add(stock_item)
                db.session.flush()

            # Update stock
            stock_item.quantity           += item["quantity"]
            stock_item.last_purchase_rate  = item["rate"]
            stock_item.purchase_rate       = item["rate"]
            stock_item.gst_percent         = item["gst"]
            stock_item.last_updated        = date.today()

            purchase_history = StockPurchaseHistory(
                stock_item_id=stock_item.id,
                purchase_invoice_id=purchase_inv.id,
                quantity=item["quantity"],
                purchase_rate=item["rate"],
                gst_percent=item["gst"],
                purchase_date=date.fromisoformat(invoice_date)
            )
            db.session.add(purchase_history)

            inv_item = PurchaseInvoiceItem(
                purchase_invoice_id=purchase_inv.id,
                stock_item_id=stock_item.id,
                description=item["description"],
                quantity=item["quantity"],
                unit=item["unit"],
                purchase_rate=item["rate"],
                gst_percent=item["gst"],
                total_amount=item["total"]
            )
            db.session.add(inv_item)

        # Update supplier pending payable
        if supplier_id:
            supplier = Client.query.get(int(supplier_id))
            if supplier:
                supplier.pending = (supplier.pending or 0) + grand_total
                supplier.last_payment = date.today()

        db.session.commit()

        # Handle file upload
        if "invoice_file" in request.files:
            file = request.files["invoice_file"]
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{invoice_id}_{file.filename}")
                filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(filepath)
                purchase_inv.file_path = filepath
                db.session.commit()

        flash(f"Purchase invoice {invoice_id} created successfully!")
        return redirect(url_for("purchase_invoice_list"))

    return render_template("purchase_form.html",
                           suppliers=suppliers,
                           today=str(date.today()))

@app.route("/purchase/view/<invoice_id>")
@login_required
def purchase_invoice_view(invoice_id):
    company_id = get_current_company()
    invoice = PurchaseInvoice.query.filter_by(invoice_id=invoice_id, company_id=company_id).first_or_404()
    return render_template("purchase_view.html", invoice=invoice)

"""@app.route("/purchase/pay/<int:pk>", methods=["POST"])
@login_required
def purchase_make_payment(pk):
    company_id = get_current_company()
    invoice = PurchaseInvoice.query.filter_by(id=pk, company_id=company_id).first_or_404()
    
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
    
    db.session.commit()
    flash(f"Payment of ₹{amount:,.2f} recorded!")
    return redirect(url_for("purchase_invoice_view", invoice_id=invoice.invoice_id))"""
@app.route("/purchase/pay/<int:pk>", methods=["POST"])
@login_required
def purchase_make_payment(pk):
    company_id = get_current_company()
    invoice = PurchaseInvoice.query.filter_by(id=pk, company_id=company_id).first_or_404()

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

    db.session.commit()
    flash(f"Payment of ₹{amount:,.2f} via {pay_mode} recorded. {narration}")
    return redirect(url_for("purchase_invoice_view", invoice_id=invoice.invoice_id))

# ─────────────────────────────────────────────────────────────────────────────
# ── Invoices ──────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/invoice/list")
@login_required
def invoice_list():
    company_id    = get_current_company()
    filter_status = request.args.get("status", "All")

    # Map template tab names -> DB status values
    status_map = {
        "paid":    "Paid",
        "partial": "Partial",
        "pending": "Draft",
    }

    query = Invoice.query.filter_by(company_id=company_id)
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
        })

    return render_template("invoice_list.html",
                           invoices=invoices,
                           current_status=filter_status)


"""@app.route("/invoice/new", methods=["GET", "POST"])
@login_required
def invoice_new():
    company_id = get_current_company()
    clients    = Client.query.filter_by(company_id=company_id).all()

    edit_id  = request.args.get("edit")
    existing = Invoice.query.filter_by(invoice_id=edit_id, company_id=company_id).first() if edit_id else None

    if request.method == "POST":
        item_codes   = request.form.getlist("item_code[]")
        descriptions = request.form.getlist("description[]")
        qtys         = request.form.getlist("qty[]")
        rates        = request.form.getlist("rate[]")
        discounts    = request.form.getlist("discount[]")

        subtotal = 0
        line_items = []
        for i in range(len(descriptions)):
            if descriptions[i] and descriptions[i].strip():
                qty  = float(qtys[i])  if qtys[i]  else 0
                rate = float(rates[i]) if rates[i] else 0
                disc = float(discounts[i]) if discounts[i] else 0
                total_line = qty * rate * (1 - disc / 100)
                subtotal  += total_line
                line_items.append((item_codes[i], descriptions[i], qty, rate, disc))

        tax         = subtotal * 0.18
        grand_total = subtotal + tax

        client_id_raw = request.form.get("client_id")
        client_id     = int(client_id_raw) if client_id_raw else None

        if existing:
            existing.client_id      = client_id
            existing.date           = date.fromisoformat(request.form.get("invoice_date") or str(date.today()))
            existing.status         = request.form.get("status", "Draft")
            existing.contact_person = request.form.get("contact_person", "")
            existing.email          = request.form.get("email", "")
            existing.phone          = request.form.get("phone", "")
            existing.subtotal       = subtotal
            existing.tax_amount     = tax
            existing.grand_total    = grand_total
            existing.terms          = request.form.get("terms", "")
            # rebuild line items
            InvoiceItem.query.filter_by(invoice_id=existing.id).delete()
            for code, desc, qty, rate, disc in line_items:
                si = StockItem.query.filter_by(company_id=company_id, code=code.upper()).first()
                db.session.add(InvoiceItem(
                    invoice_id=existing.id,
                    stock_item_id=si.id if si else None,
                    code=code, description=desc, qty=qty, rate=rate, discount=disc,
                ))
            db.session.commit()
            flash(f"Invoice {existing.invoice_id} updated!")
        else:
            inv_count  = Invoice.query.count()
            invoice_id = f"INV-{datetime.now().strftime('%Y%m%d')}-{inv_count+1:03d}"
            inv        = Invoice(
                invoice_id=invoice_id, company_id=company_id,
                client_id=client_id,
                date=date.fromisoformat(request.form.get("invoice_date") or str(date.today())),
                due_date=date.fromisoformat(request.form.get("due_date")) if request.form.get("due_date") else None,
                status=request.form.get("status", "Draft"),
                contact_person=request.form.get("contact_person", ""),
                email=request.form.get("email", ""),
                phone=request.form.get("phone", ""),
                subtotal=subtotal, tax_amount=tax, grand_total=grand_total,
                terms=request.form.get("terms", ""),
            )
            db.session.add(inv)
            db.session.flush()
            for code, desc, qty, rate, disc in line_items:
                si = StockItem.query.filter_by(company_id=company_id, code=code.upper()).first()
                db.session.add(InvoiceItem(
                    invoice_id=inv.id,
                    stock_item_id=si.id if si else None,
                    code=code, description=desc, qty=qty, rate=rate, discount=disc,
                ))
            db.session.commit()
            flash(f"Invoice {invoice_id} created!")

        return redirect(url_for("invoice_list"))

    return render_template("invoice.html",
                           clients=clients, invoice=existing,
                           today=str(date.today()),
                           due_date=str(date.today() + timedelta(days=30)),
                           form_data={})"""

@app.route("/invoice/new", methods=["GET", "POST"])
@login_required
def invoice_new():
    company_id = get_current_company()
    clients = Client.query.filter_by(company_id=company_id).all()

    # Check if we're editing an existing invoice
    edit_id = request.args.get("edit")
    existing_invoice = None
    if edit_id:
        existing_invoice = Invoice.query.filter_by(invoice_id=edit_id, company_id=company_id).first()
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
            "gst": gst,
            "amount_paid": amount_paid,
            "packages": packages_data,
        })

        # Check if we're updating an existing invoice
        edit_invoice_id = request.form.get("edit_invoice_id")
        if edit_invoice_id:
            # Update existing invoice
            invoice = Invoice.query.filter_by(invoice_id=edit_invoice_id, company_id=company_id).first()
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
                
                db.session.commit()
                flash(f"Customer invoice {invoice.invoice_id} updated successfully!")
                return redirect(url_for("invoice_list"))
        else:
            # Create new invoice
            cust_count = Invoice.query.filter_by(company_id=company_id).filter(Invoice.invoice_id.like("CUST-%")).count()
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
            db.session.add(inv)
            db.session.commit()
            
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
            "shipper_address": meta.get("shipper_address", ""),
            "receiver_name": meta.get("receiver_name", ""),
            "receiver_phone": meta.get("receiver_phone", ""),
            "receiver_address": meta.get("receiver_address", ""),
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
            "amount_paid": meta.get("amount_paid", existing_invoice.paid_amount or 0),
            "payment_mode": meta.get("payment_mode", "cash"),
            "upi_app": meta.get("upi_app", ""),
            "upi_ref": meta.get("upi_ref", ""),
            "cheque_no": meta.get("cheque_no", ""),
            "cheque_date": meta.get("cheque_date", ""),
            "cheque_bank": meta.get("cheque_bank", ""),
            "notes": existing_invoice.email or "",
            "docket_no": meta.get("docket_no", ""),
        }
        
        docket_no = meta.get("docket_no", "")
        
        # Get packages from meta
        packages = meta.get("packages", [])
        
        # If no packages in meta, create default empty package
        if not packages:
            packages = [{"name": "", "type": "", "qty": 1, "length": "", "width": "", "height": "", "weight": "", "rate": 0}]
    else:
        # New invoice - default values
        cust_count = Invoice.query.filter_by(company_id=company_id).filter(Invoice.invoice_id.like("CUST-%")).count()
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
                           today=str(date.today()))

@app.route("/invoice/customer/update", methods=["POST"])
@login_required
def invoice_customer_update():
    """Update an existing customer invoice"""
    company_id = get_current_company()
    edit_invoice_id = request.form.get("edit_invoice_id")
    
    # Find the existing invoice
    invoice = Invoice.query.filter_by(invoice_id=edit_invoice_id, company_id=company_id).first()
    if not invoice:
        flash("Invoice not found")
        return redirect(url_for("invoice_list"))
    
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
    freight = float(request.form.get("freight_amount", 0) or 0)
    fuel = float(request.form.get("fuel_surcharge", 0) or 0)
    other = float(request.form.get("other_charges", 0) or 0)
    base = freight + fuel + other
    gst = round(base * 0.18, 2)
    grand_total = round(base + gst, 2)
    amount_paid = float(request.form.get("amount_paid", 0) or 0)
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
        "gst": gst,
        "amount_paid": amount_paid,
        "packages": packages_data,
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

    db.session.commit()

    flash(f"Customer invoice {invoice.invoice_id} updated successfully!")
    return redirect(url_for("invoice_list"))

@app.route("/invoice/view/<invoice_id>")
@login_required
def invoice_view(invoice_id):
    company_id = get_current_company()
    inv        = Invoice.query.filter_by(invoice_id=invoice_id, company_id=company_id).first_or_404()

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
        # Shipment fields unpacked from JSON stored in inv.terms
        "docket_no":        meta.get("docket_no", inv.invoice_id),
        "shipper_name":     meta.get("shipper_name", inv.contact_person or ""),
        "shipper_address":  meta.get("shipper_address", ""),
        "receiver_name":    meta.get("receiver_name", ""),
        "receiver_phone":   meta.get("receiver_phone", ""),
        "receiver_address": meta.get("receiver_address", ""),
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
        "fuel_charge":      meta.get("fuel", 0),
        "other_charges":    meta.get("other", 0),
        "notes":            inv.email or "",
        "packages":         [],
    }

    return render_template("invoice_view.html", invoice=invoice)


# ─────────────────────────────────────────────────────────────────────────────
# ── Customer Invoice (Shipment) ───────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

AWB_PREFIX   = "AHL"
AWB_START    = 81000          # first number: AHL81000
AWB_COUNTER_KEY = "awb_last" # we store the last-used counter in a tiny helper


"""def _next_awb_number(company_id: int) -> str:
    
    # Count how many customer invoices already have an AHL docket number
    existing_count = (
        Invoice.query
        .filter(
            Invoice.company_id == company_id,
            Invoice.terms.like("AWB:AHL%"),   # we embed the AWB in terms for storage
        )
        .count()
    )
    # Alternatively, just count all customer-type invoices for this company
    # (simpler and still gapless)
    cust_count = (
        Invoice.query
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
    cust_count = Invoice.query.filter_by(company_id=company_id).filter(Invoice.invoice_id.like("CUST-%")).count()
    AWB_PREFIX = "AHL"
    AWB_START = 81000
    seq = AWB_START + cust_count
    return f"{AWB_PREFIX}{seq}"

@app.route("/invoice/customer")
@login_required
def invoice_customer_new():
    """Show the blank customer / shipment invoice form."""
    company_id = get_current_company()
    clients    = Client.query.filter_by(company_id=company_id).all()

    # Auto-generate invoice ID
    cust_count = (
        Invoice.query
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
        } for s in StockItem.query.filter_by(company_id=company_id).order_by(StockItem.name).all()]),
    )


"""@app.route("/invoice/customer/save", methods=["POST"])
@login_required
def invoice_customer_save():
    
    company_id = get_current_company()

    # ── Basic fields ──────────────────────────────────────────────────────────
    client_id_raw  = request.form.get("customer_id")
    client_id      = int(client_id_raw) if client_id_raw else None
    invoice_date   = request.form.get("invoice_date") or str(date.today())
    docket_no      = request.form.get("docket_no", "")
    action         = request.form.get("action", "final")   # 'draft' or 'final'

    # ── Charges & totals ──────────────────────────────────────────────────────
    freight        = float(request.form.get("freight_amount", 0) or 0)
    fuel           = float(request.form.get("fuel_surcharge",  0) or 0)
    other          = float(request.form.get("other_charges",   0) or 0)
    base           = freight + fuel + other
    gst            = round(base * 0.18, 2)
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
        Invoice.query
        .filter_by(company_id=company_id)
        .filter(Invoice.invoice_id.like("CUST-%"))
        .count()
    )
    invoice_id = f"CUST-{datetime.now().strftime('%Y%m%d')}-{cust_count + 1:03d}"

    # ── Shipment / receiver details stored in notes / terms ──────────────────
    notes = request.form.get("notes", "")
    # Pack all extra shipment metadata into the terms field as JSON
    shipment_meta = json.dumps({
        "docket_no":        docket_no,
        "shipper_name":     request.form.get("shipper_name", ""),
        "shipper_address":  request.form.get("shipper_address", ""),
        "receiver_name":    request.form.get("receiver_name", ""),
        "receiver_phone":   request.form.get("receiver_phone", ""),
        "receiver_address": request.form.get("receiver_address", ""),
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
    })

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
        # store notes in email field (re-used as a free-text field)
        email          = notes,
    )
    db.session.add(inv)
    db.session.flush()   # get inv.id before processing stock

    # ── Packaging / consumable stock deduction ────────────────────────────────
    # Each row submitted as pkg_stock_code[], pkg_stock_qty[]
    # These represent physical items (boxes, envelopes, packing tape, etc.)
    # consumed when fulfilling this shipment.  Stock is reduced immediately.
    pkg_stock_codes = request.form.getlist("pkg_stock_code[]")
    pkg_stock_qtys  = request.form.getlist("pkg_stock_qty[]")

    stock_deductions = []   # collect for flash summary
    stock_warnings   = []   # items that went below reorder level

    for code, qty_str in zip(pkg_stock_codes, pkg_stock_qtys):
        code = (code or "").strip().upper()
        try:
            qty_used = float(qty_str or 0)
        except ValueError:
            qty_used = 0

        if not code or qty_used <= 0:
            continue

        stock_item = StockItem.query.filter_by(
            company_id=company_id, code=code
        ).first()

        if not stock_item:
            # Try matching by name (fuzzy-friendly fallback)
            stock_item = StockItem.query.filter(
                StockItem.company_id == company_id,
                StockItem.name.ilike(f"%{code}%")
            ).first()

        if not stock_item:
            continue   # item not found in inventory — skip silently

        old_qty = stock_item.quantity
        stock_item.quantity = max(0, old_qty - qty_used)
        stock_item.last_updated = date.today()

        # Log movement in StockPurchaseHistory (re-used as generic movement log)
        # Use negative quantity convention to signal a dispatch/deduction
        movement = StockPurchaseHistory(
            stock_item_id       = stock_item.id,
            purchase_invoice_id = None,   # this is a sales deduction, not a purchase
            quantity            = -qty_used,
            purchase_rate       = stock_item.unit_price,
            gst_percent         = stock_item.gst_percent or 0,
            purchase_date       = date.fromisoformat(invoice_date),
        )
        db.session.add(movement)

        stock_deductions.append(f"{qty_used:.0f}× {stock_item.name}")

        # Warn if now below reorder level
        if (stock_item.reorder_level and
                stock_item.quantity <= stock_item.reorder_level and
                old_qty > stock_item.reorder_level):
            stock_warnings.append(stock_item.name)

    # ── Also deduct package-type quantities that match inventory items ─────────
    # Users sometimes name stock items "Box", "Envelope" etc. — auto-match
    # pkg_type[] rows so the Packages table itself drives deductions when no
    # explicit pkg_stock_code is supplied.
    if not pkg_stock_codes:
        pkg_types = request.form.getlist("pkg_type[]")
        pkg_qtys  = request.form.getlist("pkg_qty[]")
        for ptype, pqty_str in zip(pkg_types, pkg_qtys):
            if not ptype:
                continue
            try:
                pqty = float(pqty_str or 0)
            except ValueError:
                pqty = 0
            if pqty <= 0:
                continue
            # look for a stock item whose name contains the package type
            si = StockItem.query.filter(
                StockItem.company_id == company_id,
                StockItem.name.ilike(f"%{ptype}%")
            ).first()
            if si:
                si.quantity = max(0, si.quantity - pqty)
                si.last_updated = date.today()
                movement = StockPurchaseHistory(
                    stock_item_id       = si.id,
                    purchase_invoice_id = None,
                    quantity            = -pqty,
                    purchase_rate       = si.unit_price,
                    gst_percent         = si.gst_percent or 0,
                    purchase_date       = date.fromisoformat(invoice_date),
                )
                db.session.add(movement)
                stock_deductions.append(f"{pqty:.0f}× {si.name} (auto)")
                if (si.reorder_level and
                        si.quantity <= si.reorder_level):
                    stock_warnings.append(si.name)

    # ── Update client pending balance if credit / unpaid ──────────────────────
    if balance > 0 and client_id:
        client = Client.query.filter_by(id=client_id, company_id=company_id).first()
        if client and hasattr(client, "pending"):
            client.pending = (client.pending or 0) + balance

    db.session.commit()

    # ── Build flash message ───────────────────────────────────────────────────
    msg = f"Customer invoice {invoice_id} (AWB: {docket_no}) saved successfully!"
    if stock_deductions:
        msg += f" Stock deducted: {', '.join(stock_deductions)}."
    if stock_warnings:
        msg += f" ⚠️ Low stock alert: {', '.join(stock_warnings)}."

    flash(msg)
    return redirect(url_for("invoice_list"))

@app.route("/invoice/customer/save", methods=["POST"])
@login_required
def invoice_customer_save():
    company_id = get_current_company()

    # ── Basic fields ──────────────────────────────────────────────────────────
    client_id_raw  = request.form.get("customer_id")
    client_id      = int(client_id_raw) if client_id_raw else None
    invoice_date   = request.form.get("invoice_date") or str(date.today())
    docket_no      = request.form.get("docket_no", "")
    action         = request.form.get("action", "final")   # 'draft' or 'final'

    # ── Charges & totals ──────────────────────────────────────────────────────
    freight        = float(request.form.get("freight_amount", 0) or 0)
    fuel           = float(request.form.get("fuel_surcharge",  0) or 0)
    other          = float(request.form.get("other_charges",   0) or 0)
    base           = freight + fuel + other
    gst            = round(base * 0.18, 2)
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
        Invoice.query
        .filter_by(company_id=company_id)
        .filter(Invoice.invoice_id.like("CUST-%"))
        .count()
    )
    invoice_id = f"CUST-{datetime.now().strftime('%Y%m%d')}-{cust_count + 1:03d}"

    # ── Shipment / receiver details stored in notes / terms ──────────────────
    notes = request.form.get("notes", "")
    
    # ── Process Packages - ADD TO INVENTORY (not deduct) ─────────────────────
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
    
    for i in range(len(pkg_names)):
        item_name = (pkg_names[i] or "").strip()
        if not item_name:
            continue
        
        qty = float(pkg_qtys[i] or 1) if pkg_qtys[i] else 1
        rate = float(pkg_rates[i] or 0) if pkg_rates[i] else 0
        pkg_type = pkg_types[i] if i < len(pkg_types) else "Box"
        
        # Generate a unique code for the stock item
        stock_count = StockItem.query.filter_by(company_id=company_id).count()
        new_code = f"PKG-{stock_count + 1:03d}"
        
        # Check if item already exists (by name)
        existing_item = StockItem.query.filter_by(
            company_id=company_id,
            name=item_name
        ).first()
        
        if existing_item:
            # Item exists - increase quantity and update rate if needed
            old_qty = existing_item.quantity
            existing_item.quantity += qty
            if rate > 0:
                existing_item.unit_price = rate
                existing_item.purchase_rate = rate
            existing_item.last_updated = date.today()
            stock_added.append(f"{qty}× {item_name} (added to existing stock)")
            
            # Log movement - Use 0 or -1 to indicate no purchase invoice (since column has NOT NULL)
            # Option 1: Set to 0 (if your DB allows) 
            # Option 2: Create a dummy purchase invoice or use a special value
            # We'll use -1 to indicate "package addition" (non-purchase)
            movement = StockPurchaseHistory(
                stock_item_id       = existing_item.id,
                purchase_invoice_id = None,  # -1 indicates package addition (not a real purchase)
                quantity            = qty,
                purchase_rate       = rate,
                gst_percent         = existing_item.gst_percent or 0,
                purchase_date       = date.fromisoformat(invoice_date),
            )
            db.session.add(movement)
            
            # Check if stock is now above reorder level
            if (existing_item.reorder_level and 
                old_qty <= existing_item.reorder_level and 
                existing_item.quantity > existing_item.reorder_level):
                stock_warnings.append(f"{existing_item.name} is now above reorder level")
        else:
            # Create new stock item
            new_item = StockItem(
                company_id      = company_id,
                code            = new_code,
                name            = item_name,
                category        = "Packaging",
                quantity        = qty,
                unit            = "pcs",
                unit_price      = rate,
                purchase_rate   = rate,
                reorder_level   = 10,
                gst_percent     = 18,
                hsn             = "",
                last_updated    = date.today(),
            )
            db.session.add(new_item)
            db.session.flush()
            
            # Log movement - Use -1 to indicate package addition
            movement = StockPurchaseHistory(
                stock_item_id       = new_item.id,
                purchase_invoice_id = None,  # -1 indicates package addition
                quantity            = qty,
                purchase_rate       = rate,
                gst_percent         = 18,
                purchase_date       = date.fromisoformat(invoice_date),
            )
            db.session.add(movement)
            
            stock_added.append(f"{qty}× {item_name} (new stock item {new_code})")
    
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
        "shipper_address":  request.form.get("shipper_address", ""),
        "receiver_name":    request.form.get("receiver_name", ""),
        "receiver_phone":   request.form.get("receiver_phone", ""),
        "receiver_address": request.form.get("receiver_address", ""),
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
    })

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
    )
    db.session.add(inv)

    # ── Update client pending balance if credit / unpaid ──────────────────────
    if balance > 0 and client_id:
        client = Client.query.filter_by(id=client_id, company_id=company_id).first()
        if client and hasattr(client, "pending"):
            client.pending = (client.pending or 0) + balance

    db.session.commit()

    # ── Build flash message ───────────────────────────────────────────────────
    msg = f"Customer invoice {invoice_id} (AWB: {docket_no}) saved successfully!"
    if stock_added:
        msg += f" Stock added: {', '.join(stock_added)}."
    if stock_warnings:
        msg += f" ℹ️ {', '.join(stock_warnings)}."

    flash(msg)
    return redirect(url_for("invoice_list"))"""

@app.route("/invoice/customer/save", methods=["POST"])
@login_required
def invoice_customer_save():
    """Save a customer / shipment invoice submitted from invoice.html."""
    company_id = get_current_company()

    # ── Basic fields ──────────────────────────────────────────────────────────
    client_id_raw  = request.form.get("customer_id")
    client_id      = int(client_id_raw) if client_id_raw else None
    invoice_date   = request.form.get("invoice_date") or str(date.today())
    docket_no      = request.form.get("docket_no", "")
    action         = request.form.get("action", "final")   # 'draft' or 'final'

    # ── Charges & totals ──────────────────────────────────────────────────────
    freight        = float(request.form.get("freight_amount", 0) or 0)
    fuel           = float(request.form.get("fuel_surcharge",  0) or 0)
    other          = float(request.form.get("other_charges",   0) or 0)
    base           = freight + fuel + other
    gst            = round(base * 0.18, 2)
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
        Invoice.query
        .filter_by(company_id=company_id)
        .filter(Invoice.invoice_id.like("CUST-%"))
        .count()
    )
    invoice_id = f"CUST-{datetime.now().strftime('%Y%m%d')}-{cust_count + 1:03d}"

    # ── Shipment / receiver details stored in notes / terms ──────────────────
    notes = request.form.get("notes", "")
    
    # ── Process Packages - ADD TO INVENTORY ─────────────────────────────────────
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
    
    for i in range(len(pkg_names)):
        item_name = (pkg_names[i] or "").strip()
        if not item_name:
            continue
        
        qty = float(pkg_qtys[i] or 1) if pkg_qtys[i] else 1
        rate = float(pkg_rates[i] or 0) if pkg_rates[i] else 0
        pkg_type = pkg_types[i] if i < len(pkg_types) else "Box"
        
        # Check if item already exists (by name)
        existing_item = StockItem.query.filter_by(
            company_id=company_id,
            name=item_name
        ).first()
        
        if existing_item:
            old_qty = existing_item.quantity
            existing_item.quantity += qty
            if rate > 0:
                existing_item.unit_price = rate
                existing_item.purchase_rate = rate
            existing_item.last_updated = date.today()
            stock_added.append(f"{qty}× {item_name} (added to existing stock)")
            
            # Log movement
            movement = StockPurchaseHistory(
                stock_item_id       = existing_item.id,
                purchase_invoice_id = None,
                quantity            = qty,
                purchase_rate       = rate,
                gst_percent         = existing_item.gst_percent or 0,
                purchase_date       = date.fromisoformat(invoice_date),
            )
            db.session.add(movement)
        else:
            # Generate a unique code for the stock item
            stock_count = StockItem.query.filter_by(company_id=company_id).count()
            new_code = f"PKG-{stock_count + 1:03d}"
            
            # Create new stock item
            new_item = StockItem(
                company_id      = company_id,
                code            = new_code,
                name            = item_name,
                category        = "Packaging",
                quantity        = qty,
                unit            = "pcs",
                unit_price      = rate,
                purchase_rate   = rate,
                reorder_level   = 10,
                gst_percent     = 18,
                hsn             = "",
                last_updated    = date.today(),
            )
            db.session.add(new_item)
            db.session.flush()
            
            movement = StockPurchaseHistory(
                stock_item_id       = new_item.id,
                purchase_invoice_id = None,
                quantity            = qty,
                purchase_rate       = rate,
                gst_percent         = 18,
                purchase_date       = date.fromisoformat(invoice_date),
            )
            db.session.add(movement)
            stock_added.append(f"{qty}× {item_name} (new stock item {new_code})")
    
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
        "shipper_address":  request.form.get("shipper_address", ""),
        "receiver_name":    request.form.get("receiver_name", ""),
        "receiver_phone":   request.form.get("receiver_phone", ""),
        "receiver_address": request.form.get("receiver_address", ""),
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
    })

    # CREATE INVOICE WITHOUT paid_amount/balance in constructor
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
    )
    
    # SET paid_amount and balance AFTER creation
    inv.paid_amount = amount_paid
    inv.balance = balance
    
    db.session.add(inv)
    db.session.flush()  # Get the ID

    # ── RECORD PAYMENT IN CASH IN HAND OR BANK ACCOUNT ──────────────────────────
    if amount_paid > 0:
        transaction_date = date.fromisoformat(invoice_date)
        
        if payment_mode == "cash":
            # Record in Cash in Hand
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
            db.session.add(cash_txn)
            
        elif payment_mode == "online":
            # Record in Bank Account
            bank_account = BankAccount.query.filter_by(
                company_id=company_id, 
                status='Active'
            ).first()
            
            if not bank_account:
                # Create a default bank account
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
                db.session.add(bank_account)
                db.session.flush()
            else:
                bank_account.balance += amount_paid
                bank_account.updated_at = datetime.utcnow()
            
            # Record bank transaction
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
            db.session.add(bank_txn)
            
        elif payment_mode == "cheque":
            # Record in Bank Account
            bank_account = BankAccount.query.filter_by(
                company_id=company_id, 
                status='Active'
            ).first()
            
            if not bank_account:
                # Create a default bank account
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
                db.session.add(bank_account)
                db.session.flush()
            else:
                bank_account.balance += amount_paid
                bank_account.updated_at = datetime.utcnow()
            
            # Record cheque transaction
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
            db.session.add(bank_txn)

    # ── Update client pending balance if credit / unpaid ──────────────────────
    if balance > 0 and client_id:
        client = Client.query.filter_by(id=client_id, company_id=company_id).first()
        if client and hasattr(client, "pending"):
            client.pending = (client.pending or 0) + balance

    db.session.commit()

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
    """Return list of suppliers for the dropdown"""
    company_id = get_current_company()
    suppliers = Client.query.filter(
        Client.company_id == company_id,
        db.or_(Client.client_type == "Supplier", Client.client_type == "Both")
    ).order_by(Client.name).all()
    
    return jsonify([{
        "id": s.id,
        "name": s.name,
        "gst": s.gst_number or ""
    } for s in suppliers])

# ─────────────────────────────────────────────────────────────────────────────
# ── Shipper Invoice (estimate.html) ──────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

"""def _get_available_dockets(company_id):
    
    used_invoice_ids = set()
    shipper_estimates = Estimate.query.filter_by(company_id=company_id).all()
    for est in shipper_estimates:
        if est.terms:
            try:
                t = json.loads(est.terms)
                lid = t.get("linked_invoice_id", "")
                if lid:
                    used_invoice_ids.add(lid)
            except (ValueError, TypeError):
                pass

    all_cust = Invoice.query.filter_by(company_id=company_id).filter(Invoice.invoice_id.like("CUST-%")).order_by(Invoice.date.desc()).all()

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
    used_invoice_ids = set()
    shipper_estimates = Estimate.query.filter_by(company_id=company_id).all()
    
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

    all_cust = Invoice.query.filter_by(company_id=company_id).filter(Invoice.invoice_id.like("CUST-%")).order_by(Invoice.date.desc()).all()

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
    company_id = get_current_company()
    all_cust = Invoice.query.filter_by(company_id=company_id).filter(Invoice.invoice_id.like("CUST-%")).all()
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
    company_id    = get_current_company()
    filter_status = request.args.get("status", "All")
    query         = Estimate.query.filter_by(company_id=company_id)
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
    company_id = get_current_company()
    clients    = Client.query.filter_by(company_id=company_id).all()

    edit_id  = request.args.get("edit")
    existing = Estimate.query.filter_by(estimate_id=edit_id, company_id=company_id).first() if edit_id else None

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
            EstimateItem.query.filter_by(estimate_id=existing.id).delete()
            for code, desc, qty, rate, disc in line_items:
                si = StockItem.query.filter_by(company_id=company_id, code=code.upper()).first()
                db.session.add(EstimateItem(
                    estimate_id=existing.id,
                    stock_item_id=si.id if si else None,
                    code=code, description=desc, qty=qty, rate=rate, discount=disc,
                ))
            db.session.commit()
            flash(f"Estimate {existing.estimate_id} updated!")
        else:
            est_count   = Estimate.query.count()
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
            db.session.add(est)
            db.session.flush()
            for code, desc, qty, rate, disc in line_items:
                si = StockItem.query.filter_by(company_id=company_id, code=code.upper()).first()
                db.session.add(EstimateItem(
                    estimate_id=est.id,
                    stock_item_id=si.id if si else None,
                    code=code, description=desc, qty=qty, rate=rate, discount=disc,
                ))
            db.session.commit()
            flash(f"Estimate {estimate_id} created!")

        return redirect(url_for("estimate_list"))

    valid_until = str(date.today() + timedelta(days=30))
    available_dockets = _get_available_dockets(company_id)

    # Auto-generate Shipper Invoice ID for display
    ship_count = Estimate.query.filter_by(company_id=company_id).count()
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
    company_id = get_current_company()
    clients = Client.query.filter_by(company_id=company_id).all()

    edit_id = request.args.get("edit")
    existing = Estimate.query.filter_by(estimate_id=edit_id, company_id=company_id).first() if edit_id else None

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
        existing_edit = Estimate.query.filter_by(estimate_id=edit_invoice_id, company_id=company_id).first() if edit_invoice_id else None

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
            EstimateItem.query.filter_by(estimate_id=existing_edit.id).delete()
            for item in line_items:
                db.session.add(EstimateItem(
                    estimate_id=existing_edit.id,
                    description=item["description"],
                    hs_code=item.get("hs_code", ""),
                    unit=item.get("unit", "Pc"),
                    qty=item["qty"],
                    rate=item["rate"],
                    discount=0,
                ))
            
            db.session.commit()
            flash(f"Shipper Invoice {existing_edit.estimate_id} updated successfully!")
            return redirect(url_for("estimate_list"))
        
        # Create new
        ship_count = Estimate.query.filter_by(company_id=company_id).count()
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
        db.session.add(est)
        db.session.flush()

        for item in line_items:
            db.session.add(EstimateItem(
                estimate_id=est.id,
                description=item["description"],
                hs_code=item.get("hs_code", ""),
                unit=item.get("unit", "Pc"),
                qty=item["qty"],
                rate=item["rate"],
                discount=0,
            ))
        
        db.session.commit()
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
    ship_count = Estimate.query.filter_by(company_id=company_id).count()
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
    company_id = get_current_company()
    est = Estimate.query.filter_by(estimate_id=estimate_id, company_id=company_id).first_or_404()

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
    }

    return render_template("estimate_view.html", estimate=estimate)

@app.route("/estimate/save", methods=["POST"])
@login_required
def estimate_save():
    """Save a Shipper Invoice"""
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
    })

    edit_invoice_id = request.form.get("edit_invoice_id", "").strip()
    existing = Estimate.query.filter_by(estimate_id=edit_invoice_id, company_id=company_id).first() if edit_invoice_id else None

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
        EstimateItem.query.filter_by(estimate_id=existing.id).delete()
        for item in line_items:
            db.session.add(EstimateItem(
                estimate_id=existing.id,
                description=item["description"],
                qty=item["qty"],
                rate=item["rate"],
                discount=0,
            ))
        
        db.session.commit()
        flash(f"Shipper Invoice {existing.estimate_id} updated successfully!")
        return redirect(url_for("estimate_list"))
    
    # Create new
    ship_count = Estimate.query.filter_by(company_id=company_id).count()
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
    db.session.add(est)
    db.session.flush()

    for item in line_items:
        db.session.add(EstimateItem(
            estimate_id=est.id,
            description=item["description"],
            qty=item["qty"],
            rate=item["rate"],
            discount=0,
        ))
    
    db.session.commit()
    flash(f"Shipper Invoice {estimate_id} created successfully!")
    return redirect(url_for("estimate_list"))

# ─────────────────────────────────────────────────────────────────────────────
# ── Super Admin ───────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/admin/dashboard")
@login_required
@super_admin_required
def admin_dashboard():
    stats = {
        "total_companies":  Company.query.count(),
        "total_users":      CompanyUser.query.count(),
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
    company = get_company_by_id(company_id)
    users   = CompanyUser.query.filter_by(company_id=company_id).all()
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
        db.session.commit()
        flash(f"Company plan updated to {plan.name}")
    return redirect(url_for("admin_company_detail", company_id=company_id))


@app.route("/admin/company/<company_id>/toggle-status", methods=["POST"])
@login_required
@super_admin_required
def admin_toggle_company_status(company_id):
    company = get_company_by_id(company_id)
    if company:
        company.is_active = not company.is_active
        db.session.commit()
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
    company_id = get_current_company()
    employees  = CompanyUser.query.filter_by(company_id=company_id).all()
    return render_template("employees.html", employees=employees)


@app.route("/employees/add", methods=["GET", "POST"])
@login_required
@owner_required
def employee_add():
    company_id = get_current_company()
    can_add, msg = check_company_limit(company_id, "user")
    if not can_add:
        flash(msg)
        return redirect(url_for("employee_list"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        emp_count = CompanyUser.query.count()
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
        db.session.add(new_emp)
        db.session.commit()
        flash("Employee added!")
        return redirect(url_for("employee_list"))
    return render_template("employee_form.html")


@app.route("/employees/toggle/<user_id>", methods=["POST"])
@login_required
@owner_required
def employee_toggle(user_id):
    company_id = get_current_company()
    emp        = CompanyUser.query.filter_by(user_id=user_id, company_id=company_id).first_or_404()
    emp.is_active = not emp.is_active
    db.session.commit()
    flash(f"Employee {'activated' if emp.is_active else 'deactivated'}.")
    return redirect(url_for("employee_list"))


# ─────────────────────────────────────────────────────────────────────────────
# ── Product Lookup API ────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
@app.route("/api/product/<code>")
@login_required
def api_product_lookup(code):
    company_id = get_current_company()
    code_clean = code.strip().upper()
    item = StockItem.query.filter_by(company_id=company_id, code=code_clean).first()
    if not item:
        item = StockItem.query.filter(
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
    company_id = get_current_company()
    q = request.args.get("q", "").strip().upper()
    if not q:
        return jsonify({"results": []})
    items = StockItem.query.filter(
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
    query = CashTransaction.query.filter(
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
    all_income = CashTransaction.query.filter_by(company_id=company_id, type='income').all()
    all_expense = CashTransaction.query.filter_by(company_id=company_id, type='expense').all()
    current_balance = sum(t.amount for t in all_income) - sum(t.amount for t in all_expense)
    
    # Format transactions for template
    running_balance = 0
    all_transactions = CashTransaction.query.filter_by(company_id=company_id).order_by(CashTransaction.date.asc()).all()
    
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
        db.session.add(transaction)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Transaction saved successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


@app.route("/api/cash-transaction/delete/<int:txn_id>", methods=["DELETE"])
@login_required
def delete_cash_transaction(txn_id):
    """Delete a cash transaction"""
    company_id = get_current_company()
    transaction = CashTransaction.query.filter_by(id=txn_id, company_id=company_id).first()
    
    if not transaction:
        return jsonify({'success': False, 'message': 'Transaction not found'}), 404
    
    try:
        db.session.delete(transaction)
        db.session.commit()
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
    company_id = get_current_company()
    bank_accounts = BankAccount.query.filter_by(company_id=company_id, status='Active').all()
    
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
    existing = BankAccount.query.filter_by(company_id=company_id, account_number=account_number).first()
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
    
    db.session.add(new_account)
    
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
        db.session.add(opening_txn)
    
    db.session.commit()
    flash(f"Bank account {bank_name} - {account_name} added successfully!")
    return redirect(url_for("bank_accounts"))


@app.route("/bank-accounts/<int:account_id>/transactions")
@login_required
def bank_transactions(account_id):
    """View transactions for a specific bank account"""
    company_id = get_current_company()
    account = BankAccount.query.filter_by(id=account_id, company_id=company_id).first_or_404()
    
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
    query = BankTransaction.query.filter(
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
    company_id = get_current_company()
    account = BankAccount.query.filter_by(id=account_id, company_id=company_id).first_or_404()
    
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
    db.session.add(transaction)
    
    # Update account balance
    if txn_type == 'credit':
        account.balance += amount
    else:
        account.balance -= amount
    
    account.updated_at = datetime.utcnow()
    
    db.session.commit()
    flash(f"{'Deposit' if txn_type == 'credit' else 'Withdrawal'} of ₹{amount:,.2f} recorded successfully!")
    return redirect(url_for("bank_transactions", account_id=account_id))


@app.route("/bank-accounts/<int:account_id>/delete", methods=["GET", "POST"])
@login_required
def delete_bank_account(account_id):
    """Delete a bank account (soft delete by setting status to Inactive)"""
    company_id = get_current_company()
    account = BankAccount.query.filter_by(id=account_id, company_id=company_id).first_or_404()
    
    # Soft delete - just mark as inactive
    account.status = 'Inactive'
    db.session.commit()
    
    flash(f"Bank account {account.bank_name} - {account.account_name} has been deactivated.")
    return redirect(url_for("bank_accounts"))


@app.route("/bank-accounts/<int:account_id>/transfer", methods=["POST"])
@login_required
def bank_transfer(account_id):
    """Transfer money between bank accounts"""
    company_id = get_current_company()
    from_account = BankAccount.query.filter_by(id=account_id, company_id=company_id).first_or_404()
    
    to_account_id = request.form.get("to_account_id", type=int)
    amount = float(request.form.get("amount", 0))
    date_str = request.form.get("date")
    description = request.form.get("description", "").strip()
    reference = request.form.get("reference", "").strip()
    
    to_account = BankAccount.query.filter_by(id=to_account_id, company_id=company_id).first()
    
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
    db.session.add(debit_txn)
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
    db.session.add(credit_txn)
    to_account.balance += amount
    
    from_account.updated_at = datetime.utcnow()
    to_account.updated_at = datetime.utcnow()
    
    db.session.commit()
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
    company_id = get_current_company()
    
    # Get all loans
    all_loans = Loan.query.filter_by(company_id=company_id).all()
    
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
        db.session.add(loan)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Loan saved successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 400


@app.route("/api/loan/repayment/save", methods=["POST"])
@login_required
def save_loan_repayment():
    """Save a loan repayment"""
    company_id = get_current_company()
    data = request.get_json()
    
    try:
        loan_id = data.get('loan_id')
        loan = Loan.query.filter_by(id=loan_id, company_id=company_id).first()
        
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
        db.session.add(repayment)
        
        # Update loan status if fully repaid
        if loan.remaining_amount - repayment.amount <= 0:
            loan.status = 'Completed'
        
        db.session.commit()
        
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
    invoices = Invoice.query.filter(
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
    purchases = PurchaseInvoice.query.filter(
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
    company_id = get_current_company()
    
    # Get filter parameter
    as_on_date_str = request.args.get('as_on_date', '')
    
    if not as_on_date_str:
        as_on_date = date.today()
    else:
        as_on_date = date.fromisoformat(as_on_date_str)
    
    accounts = {}
    
    # 1. Sales/Customers (Debtors)
    clients = Client.query.filter_by(company_id=company_id).all()
    for client in clients:
        # Calculate outstanding from invoices
        invoices = Invoice.query.filter_by(company_id=company_id, client_id=client.id).all()
        total_sales = sum(i.grand_total or 0 for i in invoices)
        total_paid = sum((i.grand_total or 0) - (getattr(i, 'balance', 0) or 0) for i in invoices)
        outstanding = total_sales - total_paid
        
        if outstanding != 0:
            accounts[f"Debtors - {client.name}"] = {
                'debit': outstanding if outstanding > 0 else 0,
                'credit': abs(outstanding) if outstanding < 0 else 0
            }
    
    # 2. Suppliers (Creditors)
    suppliers = Client.query.filter(
        Client.company_id == company_id,
        db.or_(Client.client_type == "Supplier", Client.client_type == "Both")
    ).all()
    
    for supplier in suppliers:
        purchases = PurchaseInvoice.query.filter_by(company_id=company_id, supplier_id=supplier.id).all()
        total_purchases = sum(p.grand_total or 0 for p in purchases)
        total_paid = sum(p.paid_amount or 0 for p in purchases)
        outstanding = total_purchases - total_paid
        
        if outstanding != 0:
            accounts[f"Creditors - {supplier.name}"] = {
                'debit': 0,
                'credit': outstanding if outstanding > 0 else 0
            }
    
    # 3. Sales Revenue
    all_invoices = Invoice.query.filter_by(company_id=company_id).all()
    total_revenue = sum(i.grand_total or 0 for i in all_invoices)
    if total_revenue > 0:
        accounts["Sales Revenue"] = {
            'debit': 0,
            'credit': total_revenue
        }
    
    # 4. Purchase Cost
    all_purchases = PurchaseInvoice.query.filter_by(company_id=company_id).all()
    total_purchase_cost = sum(p.grand_total or 0 for p in all_purchases)
    if total_purchase_cost > 0:
        accounts["Purchase Cost"] = {
            'debit': total_purchase_cost,
            'credit': 0
        }
    
    # 5. Stock/Inventory Value
    stock_items = StockItem.query.filter_by(company_id=company_id).all()
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

@app.route("/reports/sales")
@login_required
def sales_report():
    """Sales Report - Shows all sales invoices with filters"""
    company_id = get_current_company()
    
    # Get filter parameters
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    client_id = request.args.get('client_id', type=int)
    status = request.args.get('status', 'all')
    
    # Set default dates (current month)
    if not from_date_str:
        from_date = date.today().replace(day=1)
    else:
        from_date = date.fromisoformat(from_date_str)
    
    if not to_date_str:
        to_date = date.today()
    else:
        to_date = date.fromisoformat(to_date_str)
    
    # Build query
    query = Invoice.query.filter(
        Invoice.company_id == company_id,
        Invoice.date >= from_date,
        Invoice.date <= to_date
    )
    
    if client_id:
        query = query.filter(Invoice.client_id == client_id)
    if status != 'all':
        query = query.filter(Invoice.status == status.title())
    
    invoices = query.order_by(Invoice.date.desc()).all()
    
    # Calculate totals
    total_invoices = len(invoices)
    total_amount = sum(inv.grand_total or 0 for inv in invoices)
    total_tax = sum(inv.tax_amount or 0 for inv in invoices)
    total_paid = sum((inv.grand_total or 0) - (getattr(inv, 'balance', 0) or 0) for inv in invoices)
    total_due = sum(getattr(inv, 'balance', 0) or 0 for inv in invoices)
    
    # Get clients for filter dropdown
    clients = Client.query.filter_by(company_id=company_id).order_by(Client.name).all()
    
    # Monthly summary for chart
    monthly_data = {}
    for inv in invoices:
        month_key = inv.date.strftime('%Y-%m')
        if month_key not in monthly_data:
            monthly_data[month_key] = {'month': inv.date.strftime('%b %Y'), 'amount': 0, 'count': 0}
        monthly_data[month_key]['amount'] += inv.grand_total or 0
        monthly_data[month_key]['count'] += 1
    
    monthly_summary = list(monthly_data.values())
    
    return render_template("sales_report.html",
                         active='sales_report',
                         invoices=invoices,
                         from_date=from_date,
                         to_date=to_date,
                         clients=clients,
                         selected_client=client_id,
                         selected_status=status,
                         total_invoices=total_invoices,
                         total_amount=total_amount,
                         total_tax=total_tax,
                         total_paid=total_paid,
                         total_due=total_due,
                         monthly_summary=monthly_summary,
                         today=date.today())


@app.route("/reports/purchase")
@login_required
def purchase_report():
    """Purchase Report - Shows all purchase invoices with filters"""
    company_id = get_current_company()
    
    # Get filter parameters
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    supplier_id = request.args.get('supplier_id', type=int)
    status = request.args.get('status', 'all')
    
    # Set default dates (current month)
    if not from_date_str:
        from_date = date.today().replace(day=1)
    else:
        from_date = date.fromisoformat(from_date_str)
    
    if not to_date_str:
        to_date = date.today()
    else:
        to_date = date.fromisoformat(to_date_str)
    
    # Build query
    query = PurchaseInvoice.query.filter(
        PurchaseInvoice.company_id == company_id,
        PurchaseInvoice.date >= from_date,
        PurchaseInvoice.date <= to_date
    )
    
    if supplier_id:
        query = query.filter(PurchaseInvoice.supplier_id == supplier_id)
    if status != 'all':
        query = query.filter(PurchaseInvoice.status == status.title())
    
    purchases = query.order_by(PurchaseInvoice.date.desc()).all()
    
    # Calculate totals
    total_purchases = len(purchases)
    total_amount = sum(p.grand_total or 0 for p in purchases)
    total_tax = sum(p.tax_amount or 0 for p in purchases)
    total_paid = sum(p.paid_amount or 0 for p in purchases)
    total_due = sum(p.balance or 0 for p in purchases)
    
    # Get suppliers for filter dropdown
    suppliers = Client.query.filter(
        Client.company_id == company_id,
        db.or_(Client.client_type == "Supplier", Client.client_type == "Both")
    ).order_by(Client.name).all()
    
    # Monthly summary for chart
    monthly_data = {}
    for p in purchases:
        month_key = p.date.strftime('%Y-%m')
        if month_key not in monthly_data:
            monthly_data[month_key] = {'month': p.date.strftime('%b %Y'), 'amount': 0, 'count': 0}
        monthly_data[month_key]['amount'] += p.grand_total or 0
        monthly_data[month_key]['count'] += 1
    
    monthly_summary = list(monthly_data.values())
    
    return render_template("purchase_report.html",
                         active='purchase_report',
                         purchases=purchases,
                         from_date=from_date,
                         to_date=to_date,
                         suppliers=suppliers,
                         selected_supplier=supplier_id,
                         selected_status=status,
                         total_purchases=total_purchases,
                         total_amount=total_amount,
                         total_tax=total_tax,
                         total_paid=total_paid,
                         total_due=total_due,
                         monthly_summary=monthly_summary,
                         today=date.today())


@app.route("/reports/stock")
@login_required
def stock_report():
    """Stock Report - Shows current inventory status"""
    company_id = get_current_company()
    
    # Get filter parameters
    category = request.args.get('category', 'all')
    stock_status = request.args.get('stock_status', 'all')
    search = request.args.get('search', '')
    
    # Build query
    query = StockItem.query.filter(StockItem.company_id == company_id)
    
    if category != 'all':
        query = query.filter(StockItem.category == category)
    
    if search:
        query = query.filter(
            db.or_(
                StockItem.name.ilike(f'%{search}%'),
                StockItem.code.ilike(f'%{search}%')
            )
        )
    
    stock_items = query.order_by(StockItem.name).all()
    
    # Filter by stock status
    filtered_items = []
    for item in stock_items:
        if stock_status == 'all':
            filtered_items.append(item)
        elif stock_status == 'low' and 0 < item.quantity <= (item.reorder_level or 10):
            filtered_items.append(item)
        elif stock_status == 'out' and item.quantity <= 0:
            filtered_items.append(item)
        elif stock_status == 'in' and item.quantity > (item.reorder_level or 10):
            filtered_items.append(item)
        else:
            filtered_items.append(item)
    
    # Calculate summary
    total_items = len(stock_items)
    total_value = sum((item.purchase_rate or item.unit_price or 0) * item.quantity for item in stock_items)
    low_stock_count = sum(1 for i in stock_items if 0 < i.quantity <= (i.reorder_level or 10))
    out_stock_count = sum(1 for i in stock_items if i.quantity <= 0)
    in_stock_count = total_items - low_stock_count - out_stock_count
    
    # Get unique categories for filter
    categories = list(set(item.category for item in stock_items if item.category))
    
    # Top selling items (based on invoice items)
    invoice_items = db.session.query(
        InvoiceItem.code,
        InvoiceItem.description,
        db.func.sum(InvoiceItem.qty).label('total_qty')
    ).join(Invoice).filter(
        Invoice.company_id == company_id
    ).group_by(InvoiceItem.code).order_by(db.func.sum(InvoiceItem.qty).desc()).limit(10).all()
    
    top_items = [{'code': i[0], 'name': i[1], 'qty': i[2] or 0} for i in invoice_items]
    
    return render_template("stock_report.html",
                         active='stock_report',
                         stock_items=filtered_items,
                         categories=categories,
                         selected_category=category,
                         selected_status=stock_status,
                         search_query=search,
                         total_items=total_items,
                         total_value=total_value,
                         in_stock_count=in_stock_count,
                         low_stock_count=low_stock_count,
                         out_stock_count=out_stock_count,
                         top_items=top_items,
                         today=date.today())


@app.route("/reports/tax")
@login_required
def tax_report():
    """Tax/GST Report - Shows GST summary"""
    company_id = get_current_company()
    
    # Get filter parameters
    from_date_str = request.args.get('from_date', '')
    to_date_str = request.args.get('to_date', '')
    tax_type = request.args.get('tax_type', 'all')
    
    # Set default dates (current quarter)
    if not from_date_str:
        # First day of current quarter
        current_month = date.today().month
        if current_month <= 3:
            from_date = date(date.today().year, 1, 1)
        elif current_month <= 6:
            from_date = date(date.today().year, 4, 1)
        elif current_month <= 9:
            from_date = date(date.today().year, 7, 1)
        else:
            from_date = date(date.today().year, 10, 1)
    else:
        from_date = date.fromisoformat(from_date_str)
    
    if not to_date_str:
        to_date = date.today()
    else:
        to_date = date.fromisoformat(to_date_str)
    
    # Get sales invoices (Output GST)
    sales_invoices = Invoice.query.filter(
        Invoice.company_id == company_id,
        Invoice.date >= from_date,
        Invoice.date <= to_date,
        Invoice.status != 'Draft'
    ).all()
    
    # Get purchase invoices (Input GST)
    purchase_invoices = PurchaseInvoice.query.filter(
        PurchaseInvoice.company_id == company_id,
        PurchaseInvoice.date >= from_date,
        PurchaseInvoice.date <= to_date,
        PurchaseInvoice.status != 'Draft'
    ).all()
    
    # Calculate Output GST (from sales)
    output_cgst = sum(i.tax_amount / 2 for i in sales_invoices if i.tax_amount) if sales_invoices else 0
    output_sgst = output_cgst
    output_igst = 0  # For interstate sales, would be calculated separately
    
    # Calculate Input GST (from purchases)
    input_cgst = sum(p.tax_amount / 2 for p in purchase_invoices if p.tax_amount) if purchase_invoices else 0
    input_sgst = input_cgst
    input_igst = 0
    
    # Net GST payable
    net_cgst = output_cgst - input_cgst
    net_sgst = output_sgst - input_sgst
    net_igst = output_igst - input_igst
    total_net_gst = net_cgst + net_sgst + net_igst
    
    # Monthly GST summary
    monthly_gst = {}
    for inv in sales_invoices:
        month_key = inv.date.strftime('%Y-%m')
        if month_key not in monthly_gst:
            monthly_gst[month_key] = {
                'month': inv.date.strftime('%b %Y'),
                'sales_amount': 0,
                'gst_amount': 0,
                'purchase_amount': 0,
                'input_gst': 0
            }
        monthly_gst[month_key]['sales_amount'] += inv.grand_total or 0
        monthly_gst[month_key]['gst_amount'] += inv.tax_amount or 0
    
    for pur in purchase_invoices:
        month_key = pur.date.strftime('%Y-%m')
        if month_key not in monthly_gst:
            monthly_gst[month_key] = {
                'month': pur.date.strftime('%b %Y'),
                'sales_amount': 0,
                'gst_amount': 0,
                'purchase_amount': 0,
                'input_gst': 0
            }
        monthly_gst[month_key]['purchase_amount'] += pur.grand_total or 0
        monthly_gst[month_key]['input_gst'] += pur.tax_amount or 0
    
    monthly_summary = list(monthly_gst.values())
    monthly_summary.sort(key=lambda x: x['month'])
    
    # HSN-wise summary
    hsn_summary = {}
    for inv in sales_invoices:
        for item in inv.items:
            hsn = item.code[:6] if item.code else 'Other'
            if hsn not in hsn_summary:
                hsn_summary[hsn] = {'quantity': 0, 'value': 0, 'gst': 0}
            hsn_summary[hsn]['quantity'] += item.qty or 0
            hsn_summary[hsn]['value'] += (item.qty or 0) * (item.rate or 0)
            hsn_summary[hsn]['gst'] += ((item.qty or 0) * (item.rate or 0) * 0.18)
    
    return render_template("tax_report.html",
                         active='tax_report',
                         from_date=from_date,
                         to_date=to_date,
                         sales_invoices=sales_invoices,
                         purchase_invoices=purchase_invoices,
                         total_sales=sum(i.grand_total or 0 for i in sales_invoices),
                         total_purchases=sum(p.grand_total or 0 for p in purchase_invoices),
                         output_cgst=output_cgst,
                         output_sgst=output_sgst,
                         input_cgst=input_cgst,
                         input_sgst=input_sgst,
                         net_cgst=net_cgst,
                         net_sgst=net_sgst,
                         total_net_gst=total_net_gst,
                         monthly_summary=monthly_summary,
                         hsn_summary=hsn_summary,
                         today=date.today())


@app.route("/reports/profit-loss")
@login_required
def profit_loss():
    """Profit & Loss Statement"""
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
    sales_invoices = Invoice.query.filter(
        Invoice.company_id == company_id,
        Invoice.date >= from_date,
        Invoice.date <= to_date,
        Invoice.status != 'Draft'
    ).all()
    
    total_revenue = sum(i.grand_total or 0 for i in sales_invoices)
    
    # EXPENSES: Purchase Cost
    purchase_invoices = PurchaseInvoice.query.filter(
        PurchaseInvoice.company_id == company_id,
        PurchaseInvoice.date >= from_date,
        PurchaseInvoice.date <= to_date,
        PurchaseInvoice.status != 'Draft'
    ).all()
    
    cost_of_goods_sold = sum(p.grand_total or 0 for p in purchase_invoices)
    
    # GROSS PROFIT
    gross_profit = total_revenue - cost_of_goods_sold
    
    # Calculate other income (cash transactions)
    cash_income = CashTransaction.query.filter(
        CashTransaction.company_id == company_id,
        CashTransaction.type == 'income',
        CashTransaction.date >= from_date,
        CashTransaction.date <= to_date
    ).all()
    other_income = sum(i.amount for i in cash_income)
    
    # Calculate expenses (cash transactions)
    cash_expenses = CashTransaction.query.filter(
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

@app.route("/backup")
@login_required
def backup():
    """Backup data"""
    company_id = get_current_company()
    return render_template("backup.html", active='backup')

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
    company    = get_company_by_id(company_id)
    users      = CompanyUser.query.filter_by(company_id=company_id).all()
    
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
        db.session.commit()
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

    if CompanyUser.query.filter_by(company_id=company_id, email=email).first():
        flash("A user with this email already exists in your company.")
        return redirect(url_for("company_settings"))

    emp_count = CompanyUser.query.count()
    emp_id    = f"EMP{emp_count + 1:03d}"
    new_user  = CompanyUser(
        user_id=emp_id, company_id=company_id,
        email=email, password_hash=hash_password(password),
        full_name=full_name, role=role,
        department=department, phone=phone,
        is_active=True, created_at=date.today()
    )
    db.session.add(new_user)
    db.session.commit()
    flash(f"User '{full_name}' added successfully.")
    return redirect(url_for("company_settings"))


@app.route("/company/remove-user/<user_id>")
@login_required
@owner_required
def remove_company_user(user_id):
    company_id = get_current_company()
    user = CompanyUser.query.filter_by(user_id=user_id, company_id=company_id).first()
    if user and user.role != "owner":
        user.is_active = False
        db.session.commit()
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
        db.session.commit()
        flash(f"Plan upgraded to {plan.name} successfully!")
    else:
        flash("Invalid plan selected.")
    return redirect(url_for("company_settings"))

# ─────────────────────────────────────────────────────────────────────────────
# ── DEBTORS & CREDITORS ───────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
#
#  Debtors  = Clients who OWE you money  (Sales Invoices with balance > 0)
#  Creditors= Suppliers you OWE money to (Purchase Invoices with balance > 0)
#
# ─────────────────────────────────────────────────────────────────────────────

def _debtor_summary(company_id):
    """
    For every client that has at least one sales invoice (paid or unpaid),
    return a summary dict with the key financial fields.
    """
    # Get all clients who have invoices
    clients_with_invoices = db.session.query(Client).join(
        Invoice, Invoice.client_id == Client.id
    ).filter(
        Client.company_id == company_id
    ).distinct().all()
    
    today   = date.today()
    rows    = []

    for c in clients_with_invoices:
        invoices = (Invoice.query
                    .filter_by(company_id=company_id, client_id=c.id)
                    .order_by(Invoice.date.desc())
                    .all())
        if not invoices:
            continue

        # Calculate total pending (unpaid balance)
        total_pending = sum(float(getattr(i, "balance", 0) or 0) for i in invoices)
        
        # Calculate total invoiced amount
        total_invoiced = sum(float(i.grand_total or 0) for i in invoices)
        
        # Calculate total paid
        total_paid = total_invoiced - total_pending

        last_invoice_date = invoices[0].date  # already desc sorted

        # nearest due invoice (unpaid, due_date set)
        unpaid       = [i for i in invoices if (float(getattr(i, "balance", 0) or 0)) > 0]
        due_invoices = [i for i in unpaid if getattr(i, "due_date", None)]
        if due_invoices:
            future  = [i for i in due_invoices if i.due_date >= today]
            nearest = min(future, key=lambda i: i.due_date) if future else \
                      max(due_invoices, key=lambda i: i.due_date)
            nearest_due_date = nearest.due_date
            nearest_due_amt  = float(getattr(nearest, "balance", 0) or 0)
        else:
            nearest_due_date = None
            nearest_due_amt  = None

        # last payment: invoice with highest amount paid
        paid_invoices = [i for i in invoices
                         if (float(i.grand_total or 0) - (float(getattr(i, "balance", 0) or 0))) > 0]
        if paid_invoices:
            last_paid_inv     = max(paid_invoices, key=lambda i: i.date)
            last_payment_date = last_paid_inv.date
            last_payment_amt  = float(last_paid_inv.grand_total or 0) - (float(getattr(last_paid_inv, "balance", 0) or 0))
        else:
            last_payment_date = None
            last_payment_amt  = None

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
            "overdue":           nearest_due_date is not None and nearest_due_date < today,
        })

    rows.sort(key=lambda r: r["total_pending"], reverse=True)
    return rows


def _creditor_summary(company_id):
    """
    For every supplier that has at least one outstanding purchase invoice.
    """
    suppliers = Client.query.filter(
        Client.company_id == company_id,
        db.or_(Client.client_type == "Supplier", Client.client_type == "Both")
    ).all()

    today = date.today()
    rows  = []

    for s in suppliers:
        invoices = (PurchaseInvoice.query
                    .filter_by(company_id=company_id, supplier_id=s.id)
                    .order_by(PurchaseInvoice.date.desc())
                    .all())
        if not invoices:
            continue

        total_pending = sum(i.balance or 0 for i in invoices)
        if total_pending <= 0:
            continue

        last_bill_date = invoices[0].date

        unpaid       = [i for i in invoices if (i.balance or 0) > 0]
        due_invoices = [i for i in unpaid if i.due_date]
        if due_invoices:
            future  = [i for i in due_invoices if i.due_date >= today]
            nearest = min(future, key=lambda i: i.due_date) if future else \
                      max(due_invoices, key=lambda i: i.due_date)
            nearest_due_date = nearest.due_date
            nearest_due_amt  = nearest.balance or 0
        else:
            nearest_due_date = None
            nearest_due_amt  = None

        paid_invs = [i for i in invoices if (i.paid_amount or 0) > 0]
        if paid_invs:
            last_paid_inv     = max(paid_invs, key=lambda i: i.date)
            last_payment_date = last_paid_inv.date
            last_payment_amt  = last_paid_inv.paid_amount or 0
        else:
            last_payment_date = None
            last_payment_amt  = None

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
            "overdue":           nearest_due_date is not None and nearest_due_date < today,
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
    company_id = get_current_company()
    c          = Client.query.filter_by(id=client_pk, company_id=company_id).first_or_404()

    invoices = (Invoice.query
                .filter_by(company_id=company_id, client_id=c.id)
                .order_by(Invoice.date.asc())
                .all())

    ledger          = []
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
        running_balance += inv.grand_total
        ledger.append({
            "date":    inv.date,
            "type":    "Invoice",
            "ref":     inv.invoice_id,
            "debit":   inv.grand_total,
            "credit":  0,
            "balance": running_balance,
            "status":  inv.status,
            "id":      inv.invoice_id,
        })
        paid = inv.grand_total - (getattr(inv, "balance", 0) or 0)
        if paid > 0:
            running_balance -= paid
            ledger.append({
                "date":    inv.date,
                "type":    "Payment Received",
                "ref":     inv.invoice_id,
                "debit":   0,
                "credit":  paid,
                "balance": running_balance,
                "status":  "",
                "id":      inv.invoice_id,
            })

    total_debit  = sum(r["debit"]  for r in ledger)
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
    company_id = get_current_company()
    s          = Client.query.filter_by(id=supplier_pk, company_id=company_id).first_or_404()

    invoices = (PurchaseInvoice.query
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
    invs = (Invoice.query
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
    invs = (PurchaseInvoice.query
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
    company_id    = get_current_company()
    all_clients   = Client.query.filter_by(company_id=company_id).order_by(Client.name).all()
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
        inv = Invoice.query.filter_by(id=inv_id, company_id=company_id).first()
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

        if inv_balance <= 0:
            inv.status = "Paid"
        elif apply > 0:
            inv.status = "Partial"

    client = Client.query.filter_by(id=entity_id, company_id=company_id).first()
    if client and hasattr(client, "pending") and client.pending:
        client.pending = max(0, (client.pending or 0) - settled)

    db.session.commit()
    flash(f"Receipt of ₹{settled:,.2f} recorded via {pay_mode}. {narration}")
    return redirect(url_for("debtors_list"))


@app.route("/payments/new")
@login_required
def payment_new():
    company_id    = get_current_company()
    all_suppliers = Client.query.filter_by(company_id=company_id).order_by(Client.name).all()
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
        inv = PurchaseInvoice.query.filter_by(id=inv_id, company_id=company_id).first()
        if not inv:
            continue

        inv_balance  = inv.balance or (inv.grand_total or 0)
        apply        = min(remaining, inv_balance)
        remaining   -= apply
        settled     += apply

        inv.balance     = inv_balance - apply
        inv.paid_amount = (inv.paid_amount or 0) + apply

        if inv.balance <= 0:
            inv.status = "Paid"
        elif apply > 0:
            inv.status = "Partial"

        if inv.supplier and hasattr(inv.supplier, "pending"):
            inv.supplier.pending = max(0, (inv.supplier.pending or 0) - apply)

    db.session.commit()
    flash(f"Payment of ₹{settled:,.2f} recorded via {pay_mode}. {narration}")
    return redirect(url_for("creditors_list"))


# ─────────────────────────────────────────────────────────────────────────────
# ── App entry point ───────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed_database()
    app.run(debug=True, port=5010)
else:
    # When run by Gunicorn / Render, seed after the app is fully loaded
    with app.app_context():
        seed_database()
