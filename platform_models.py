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
db = None


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
    role              = db.Column(db.String(50),  nullable=False, default="owner")
    subscription_plan = db.Column(db.String(20),
                            db.ForeignKey("subscription_plans.id"), nullable=True)
    created_at        = db.Column(db.Date,        nullable=False, default=date.today)
    is_active         = db.Column(db.Boolean,     nullable=False, default=True)

    plan_obj  = db.relationship("SubscriptionPlan", back_populates="registered_users")
    companies = db.relationship(
        "Company", back_populates="owner",
        foreign_keys="Company.owner_email",
        primaryjoin="RegisteredUser.email == Company.owner_email",
    )

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
    address               = db.Column(db.String(300), nullable=True)
    phone                 = db.Column(db.String(20),  nullable=True)
    logo                  = db.Column(db.String(300), nullable=True)
    created_at            = db.Column(db.Date,        nullable=False, default=date.today)
    is_active             = db.Column(db.Boolean,     nullable=False, default=True)

    # ── Storage preference chosen at registration ─────────────────────────────
    # 'local'  → SQLite file on the server  (data_db_uri = path to .db file)
    # 'cloud'  → MySQL on cloud             (data_db_uri = full mysql+pymysql:// URI)
    storage_type = db.Column(db.String(10),  nullable=False, default="local")
    data_db_uri  = db.Column(db.String(500), nullable=True)   # connection string / path

    owner     = db.relationship("RegisteredUser", back_populates="companies",
                                          foreign_keys=[owner_email])
    plan_obj  = db.relationship("SubscriptionPlan", back_populates="companies")

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
