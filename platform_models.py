"""
platform_models.py
──────────────────
YOUR data only — stored in YOUR MySQL database.
Tables: subscription_plans, registered_users, companies

This DB is always mysql+pymysql. Customers never touch it.
"""

from flask_sqlalchemy import SQLAlchemy
from datetime import date, datetime
from sqlalchemy import func

# Create SQLAlchemy instance WITHOUT binding to an app yet
# This will be initialized with init_app(app) in app.py
db = SQLAlchemy()


# ── 1. Subscription Plans ─────────────────────────────────────────────────────
class SubscriptionPlan(db.Model):
    __tablename__ = "subscription_plans"

    id            = db.Column(db.String(20),  primary_key=True)
    name          = db.Column(db.String(100), nullable=False)
    price         = db.Column(db.String(50),  nullable=False)
    max_companies = db.Column(db.String(20),  nullable=False)
    max_users     = db.Column(db.String(20),  nullable=False)
    features      = db.Column(db.Text,        nullable=True)

    companies        = db.relationship("Company",        back_populates="plan_obj")
    registered_users = db.relationship("RegisteredUser", back_populates="plan_obj")

    def __repr__(self):
        return f"<SubscriptionPlan {self.id}>"


# ── 2. Registered Users (account / subscription holders) ─────────────────────
class RegisteredUser(db.Model):
    __tablename__ = "registered_users"

    id                = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    user_id           = db.Column(db.String(20),  unique=True, nullable=False)
    email             = db.Column(db.String(255), unique=True, nullable=False)
    password_hash     = db.Column(db.String(255), nullable=False)
    full_name         = db.Column(db.String(150), nullable=False)
    phone             = db.Column(db.String(20),  nullable=True)
    address           = db.Column(db.String(300), nullable=True)
    role              = db.Column(db.String(50),  nullable=False, default="owner")
    subscription_plan = db.Column(db.String(20),
                            db.ForeignKey("subscription_plans.id"), nullable=True)
    created_at        = db.Column(db.Date,        nullable=False, default=date.today)
    is_active         = db.Column(db.Boolean,     nullable=False, default=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=True)
    email_verified = db.Column(db.Boolean, nullable=False, default=False)

    payment_status = db.Column(db.String(20),  nullable=False, default="pending")
    amount_total   = db.Column(db.Numeric(10, 2), nullable=True)
    amount_paid    = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    registered_by  = db.Column(db.String(255), nullable=True)   # super admin email who created this account
    registered_at  = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)
    custom_max_companies = db.Column(db.Integer, nullable=True)
    custom_max_users = db.Column(db.Integer, nullable=True)

    plan_obj  = db.relationship("SubscriptionPlan", back_populates="registered_users")
    companies = db.relationship(
        "Company", back_populates="owner",
        foreign_keys="Company.owner_email",
        primaryjoin="RegisteredUser.email == Company.owner_email",
    )

    @property
    def amount_pending(self):
        try:
            total = float(self.amount_total or 0)
            paid  = float(self.amount_paid or 0)
            return max(0, round(total - paid, 2))
        except (ValueError, TypeError):
            return 0

    @property
    def has_company(self):
        """True once this owner has completed the company-onboarding step."""
        return len(self.companies) > 0

    def __repr__(self):
        return f"<RegisteredUser {self.email}>"


# ── 4. Backup Records ─────────────────────────────────────────────────────────
class BackupRecord(db.Model):
    __tablename__ = "backup_records"

    id              = db.Column(db.Integer, primary_key=True, autoincrement=True)
    backup_id       = db.Column(db.String(50), unique=True, nullable=False)
    company_id      = db.Column(db.String(20), db.ForeignKey("companies.company_id"), nullable=False)
    backup_date     = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    backup_file_path= db.Column(db.String(500), nullable=False)
    file_size_mb    = db.Column(db.Float, nullable=False)
    file_hash       = db.Column(db.String(64), nullable=False)
    status          = db.Column(db.String(20), nullable=False, default="completed")
    cloud_backup    = db.Column(db.Boolean, default=False)
    cloud_location  = db.Column(db.String(500), nullable=True)
    restore_date    = db.Column(db.DateTime, nullable=True)
    restored_by     = db.Column(db.String(100), nullable=True)
    created_at      = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    company = db.relationship("Company", backref="backups")

    def __repr__(self):
        return f"<BackupRecord {self.backup_id}>"

# ── 5. Backup Schedules ──────────────────────────────────────────────────────
class BackupSchedule(db.Model):
    __tablename__ = "backup_schedules"

    id              = db.Column(db.Integer, primary_key=True, autoincrement=True)
    company_id      = db.Column(db.String(20), db.ForeignKey("companies.company_id"), nullable=False, unique=True)
    frequency       = db.Column(db.String(20), nullable=False, default="daily")  # daily, weekly, monthly
    time_of_day     = db.Column(db.String(10), nullable=False, default="00:00")
    retention_days  = db.Column(db.Integer, nullable=False, default=30)
    upload_to_cloud = db.Column(db.Boolean, default=False)
    last_backup     = db.Column(db.DateTime, nullable=True)
    next_backup     = db.Column(db.DateTime, nullable=True)
    is_active       = db.Column(db.Boolean, default=True)
    created_at      = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    company = db.relationship("Company", backref="backup_schedule")

    def __repr__(self):
        return f"<BackupSchedule {self.company_id}>"

# ── 3. Companies ──────────────────────────────────────────────────────────────
class Company(db.Model):
    __tablename__ = "companies"

    id                    = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    company_id            = db.Column(db.String(20),  unique=True, nullable=False)
    company_name          = db.Column(db.String(200), nullable=False)
    owner_email           = db.Column(db.String(255),
                                db.ForeignKey("registered_users.email"), nullable=False)
    subscription_plan     = db.Column(db.String(20),
                                db.ForeignKey("subscription_plans.id"), nullable=True)
    subscription_start    = db.Column(db.Date,        nullable=True)
    subscription_end      = db.Column(db.Date,        nullable=True)
    max_companies_allowed = db.Column(db.String(20),  nullable=True)
    max_users_per_company = db.Column(db.String(20),  nullable=True)
    gst_number            = db.Column(db.String(20),  nullable=True)
    logo_filename = db.Column(db.String(255), nullable=True)
    address               = db.Column(db.String(300), nullable=True)
    phone                 = db.Column(db.String(20),  nullable=True)
    logo                  = db.Column(db.String(300), nullable=True)
    awb_prefix   = db.Column(db.String(10),  nullable=False, default="AHL")
    awb_start    = db.Column(db.Integer,     nullable=False, default=81000)
    created_at            = db.Column(db.Date,        nullable=False, default=date.today)
    is_active             = db.Column(db.Boolean,     nullable=False, default=True)
    is_gst_registered = db.Column(db.Boolean, nullable=False, default=True)
    gst_number = db.Column(db.String(20), nullable=True, unique=True)

    hidden_on_mobile = db.Column(db.Boolean, nullable=False, default=False)
    storage_type = db.Column(db.String(10),  nullable=False, default="local")
    data_db_uri  = db.Column(db.String(500), nullable=True)   # connection string / path

    # ── WhatsApp / SMS messaging integration (optional, set in Settings) ──────
    # whatsapp_provider: 'meta_cloud' | 'aisensy' | 'gupshup' | None
    whatsapp_provider    = db.Column(db.String(20),  nullable=True)
    whatsapp_phone_id    = db.Column(db.String(50),  nullable=True)
    whatsapp_base_url = db.Column(db.String(500), nullable=True)   # Meta phone_number_id / provider account id
    whatsapp_token       = db.Column(db.Text,        nullable=True)   # ENCRYPTED at rest — see whatsapp_service.py
    whatsapp_business_no = db.Column(db.String(20),  nullable=True)   # WA number shown to customers
    whatsapp_enabled     = db.Column(db.Boolean,     nullable=False, default=False)
    whatsapp_template_delivery = db.Column(db.String(100), nullable=True)
    whatsapp_template_carrier_update = db.Column(db.String(100), nullable=True)

    sms_provider  = db.Column(db.String(20),  nullable=True)   # 'msg91' | 'twilio' | None
    sms_api_key   = db.Column(db.Text,        nullable=True)   # ENCRYPTED at rest
    sms_sender_id = db.Column(db.String(20),  nullable=True)
    sms_enabled   = db.Column(db.Boolean,     nullable=False, default=False)

    # ── Internal notify numbers (accounts dept / extra CC) ─────────────────────
    # Same idea as the repair app's ACCOUNTS_WHATSAPP_NUMBER / EXTRA_NOTIFY_NUMBER_1/2,
    # but user-entered per company instead of hardcoded env vars.
    accounts_whatsapp_number = db.Column(db.String(20), nullable=True)
    extra_notify_number_1    = db.Column(db.String(20), nullable=True)
    extra_notify_number_2    = db.Column(db.String(20), nullable=True)

    # ── WhatsApp Connect (simplified — MobiCOMM only, 3 fields) ────────────────
    # "Connected" = whatsapp_api_key is set. No separate enabled flag needed.
    whatsapp_api_key           = db.Column(db.Text,        nullable=True)  # ENCRYPTED — see whatsapp_service.py
    whatsapp_template_generate = db.Column(db.String(100), nullable=True)  # template name used on invoice CREATE
    whatsapp_template_update   = db.Column(db.String(100), nullable=True)  # template name used on invoice UPDATE

    owner     = db.relationship("RegisteredUser", back_populates="companies",
                                          foreign_keys=[owner_email])
    plan_obj  = db.relationship("SubscriptionPlan", back_populates="companies")

    @property
    def whatsapp_connected(self):
        return bool(self.whatsapp_api_key)

    @property
    def user_count(self):
        """Get the number of active users for this company from its customer database."""
        from db_router import get_customer_session
        from customer_models import CompanyUser
        
        try:
            # Get a session to this company's customer database
            cdb = get_customer_session(self.company_id)
            count = cdb.query(CompanyUser).filter_by(company_id=self.company_id, is_active=True).count()
            # Close the session to avoid memory leaks
            from db_router import close_customer_session
            close_customer_session(self.company_id)
            return count
        except Exception:
            return 0
    
    @property
    def max_users(self):
        """Get maximum allowed users for this company based on their plan."""
        try:
            return int(self.max_users_per_company)
        except (ValueError, TypeError):
            return 999

    def __repr__(self):
        return f"<Company {self.company_id} – {self.company_name}>"


# ── 6. WhatsApp Templates (per company, per event type) ───────────────────────
# The template BODY lives in Meta Business Manager / your provider dashboard —
# only the approved template NAME and param count are stored here.
class WhatsAppTemplate(db.Model):
    __tablename__ = "whatsapp_templates"

    id            = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    company_id    = db.Column(db.String(20),  db.ForeignKey("companies.company_id"), nullable=False)
    template_key  = db.Column(db.String(50),  nullable=False)   # 'invoice_created' | 'payment_reminder' | ...
    template_name = db.Column(db.String(100), nullable=False)   # exact name as approved by Meta/provider
    param_count   = db.Column(db.Integer,     nullable=False, default=0)
    language_code = db.Column(db.String(10),  nullable=False, default="en")
    is_active     = db.Column(db.Boolean,     nullable=False, default=True)
    created_at    = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)

    company = db.relationship("Company")

    __table_args__ = (
        db.UniqueConstraint("company_id", "template_key", name="uq_company_template_key"),
    )

    def __repr__(self):
        return f"<WhatsAppTemplate {self.company_id}:{self.template_key}>"


# ── 7. WhatsApp Provider Definitions (super-admin managed, API contract only) ─
# One row per provider TYPE (mobicomm, meta_cloud, aisensy, gupshup, ...).
# Companies never edit this table — only your super-admin does.
class WhatsAppProviderDefinition(db.Model):
    __tablename__ = "whatsapp_provider_definitions"

    id            = db.Column(db.Integer,  primary_key=True, autoincrement=True)
    provider_code = db.Column(db.String(30), unique=True, nullable=False)   # "mobicomm", "meta_cloud", "aisensy"
    provider_name = db.Column(db.String(100), nullable=False)               # display name

    method       = db.Column(db.String(10), nullable=False, default="POST")
    url_template = db.Column(db.Text, nullable=False)
    # e.g. "https://graph.facebook.com/v19.0/{{ config.phone_id }}/messages"

    headers_template = db.Column(db.Text, nullable=False)  # JSON string, values may contain {{ placeholders }}
    body_template    = db.Column(db.Text, nullable=False)  # JSON string, values may contain {{ placeholders }}
    body_encoding    = db.Column(db.String(10), nullable=False, default="json")  # "json" | "form"

    success_status_codes   = db.Column(db.String(50), nullable=False, default="200,201,202")  # csv
    success_path            = db.Column(db.String(150), nullable=True)  # dot-path into response JSON
    success_expected_value  = db.Column(db.String(100), nullable=True)  # only checked if success_path is set
    message_id_path         = db.Column(db.String(150), nullable=True)
    error_path              = db.Column(db.String(150), nullable=True)

    allowed_hosts   = db.Column(db.String(300), nullable=True)  # csv of hostnames this provider is allowed to hit
    timeout_seconds = db.Column(db.Integer, nullable=False, default=30)
    is_active       = db.Column(db.Boolean, nullable=False, default=True)
    created_at      = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<WhatsAppProviderDefinition {self.provider_code}>"


# ── 8. Company WhatsApp Config (per-company credentials only) ────────────────
# Links a company to a provider definition + holds ONLY that company's secrets.
# This is ADDITIVE — existing Company.whatsapp_* columns and the MobiCOMM path
# in whatsapp_service.py keep working untouched for companies not migrated here.
class CompanyWhatsAppConfig(db.Model):
    __tablename__ = "company_whatsapp_configs"

    id                     = db.Column(db.Integer, primary_key=True, autoincrement=True)
    company_id             = db.Column(db.String(20), db.ForeignKey("companies.company_id"),
                                        nullable=False, unique=True)
    provider_definition_id = db.Column(db.Integer,
                                        db.ForeignKey("whatsapp_provider_definitions.id"), nullable=False)

    # ENCRYPTED JSON blob, e.g. {"api_key": "...", "access_token": "...", "username": "..."}
    credentials_encrypted = db.Column(db.Text, nullable=False)
    # ENCRYPTED JSON blob for provider-specific non-secret-but-per-company values,
    # e.g. {"phone_id": "1234567890", "waba_number": "9198XXXXXXXX", "subdomain": "acct123"}
    extra_config_encrypted = db.Column(db.Text, nullable=True)

    template_generate = db.Column(db.String(100), nullable=True)
    template_update   = db.Column(db.String(100), nullable=True)
    template_delivery = db.Column(db.String(100), nullable=True)

    enabled    = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, onupdate=datetime.utcnow)

    company             = db.relationship("Company")
    provider_definition = db.relationship("WhatsAppProviderDefinition")

    def __repr__(self):
        return f"<CompanyWhatsAppConfig {self.company_id}>"
