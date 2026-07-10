"""
customer_models.py
──────────────────
CUSTOMER data only — stored in the customer's chosen database
(SQLite local  OR  MySQL cloud).

Uses plain SQLAlchemy (no Flask-SQLAlchemy) because engines are
managed per-company by db_router.py, not by Flask's app context.
"""

from sqlalchemy.orm import DeclarativeBase, relationship as _relationship
from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    Date, DateTime, Text, ForeignKey,
)
from datetime import datetime, date


class _Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Thin compatibility shim so all the  customer_db.Column / customer_db.Model
# references in the model classes below continue to work unchanged.
# ---------------------------------------------------------------------------
class _CustomerDB:
    Model        = _Base
    metadata     = _Base.metadata
    Column       = staticmethod(Column)
    Integer      = Integer
    String       = String
    Float        = Float
    Boolean      = Boolean
    Date         = Date
    DateTime     = DateTime
    Text         = Text
    ForeignKey   = staticmethod(ForeignKey)
    relationship = staticmethod(_relationship)


customer_db = _CustomerDB()


# ── 4. Company Users ──────────────────────────────────────────────────────────
class CompanyUser(customer_db.Model):
    __tablename__ = "company_users"

    id            = customer_db.Column(customer_db.Integer,    primary_key=True, autoincrement=True)
    user_id       = customer_db.Column(customer_db.String(20),  unique=True, nullable=False)
    company_id    = customer_db.Column(customer_db.String(20),  nullable=False)
    email         = customer_db.Column(customer_db.String(255), nullable=False)
    password_hash = customer_db.Column(customer_db.String(255), nullable=False)
    full_name     = customer_db.Column(customer_db.String(150), nullable=False)
    role          = customer_db.Column(customer_db.String(50),  nullable=False, default="employee")
    department    = customer_db.Column(customer_db.String(100), nullable=True)
    phone         = customer_db.Column(customer_db.String(20),  nullable=True)
    is_active     = customer_db.Column(customer_db.Boolean,     nullable=False, default=True)
    created_at    = customer_db.Column(customer_db.Date,        nullable=False, default=date.today)
    # Per-user permission overrides on top of the role default, e.g.
    # {"purchase": {"view": true, "create": true, "edit": false}}
    # A key present here always wins over the role's default for that
    # module/action. Absent keys fall back to the role default.
    permission_overrides = customer_db.Column(customer_db.Text, nullable=True)

    def __repr__(self):
        return f"<CompanyUser {self.user_id}>"


# ── 4b. Company Role Permissions ──────────────────────────────────────────────
# One row per (company_id, role). Lets an owner customize what "employee"
# (sales) and "accountant" can view/create/edit in *this* company, on top of
# the built-in defaults in permissions.py. No delete action is stored here —
# deletion is not part of this system.
class CompanyRolePermission(customer_db.Model):
    __tablename__ = "company_role_permissions"

    id               = customer_db.Column(customer_db.Integer,    primary_key=True, autoincrement=True)
    company_id       = customer_db.Column(customer_db.String(20), nullable=False)
    role             = customer_db.Column(customer_db.String(50), nullable=False)  # 'employee' | 'accountant'
    # JSON: {"clients": {"view": true, "create": false, "edit": false}, ...}
    permissions_json = customer_db.Column(customer_db.Text, nullable=True)
    updated_at       = customer_db.Column(customer_db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<CompanyRolePermission {self.company_id}:{self.role}>"


# ── 5. Clients (buyers, suppliers, debtors, creditors) ───────────────────────
class Client(customer_db.Model):
    __tablename__ = "clients"

    id              = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    company_id      = customer_db.Column(customer_db.String(20),  nullable=False)
    name            = customer_db.Column(customer_db.String(200), nullable=False)
    contact_person  = customer_db.Column(customer_db.String(150), nullable=True)
    client_type     = customer_db.Column(customer_db.String(30),  nullable=False, default="Business")
    phone           = customer_db.Column(customer_db.String(20),  nullable=True)
    alternate_phone = customer_db.Column(customer_db.String(20),  nullable=True)
    email           = customer_db.Column(customer_db.String(255), nullable=True)
    website         = customer_db.Column(customer_db.String(255), nullable=True)
    address_line1   = customer_db.Column(customer_db.String(300), nullable=True)
    address_line2   = customer_db.Column(customer_db.String(300), nullable=True)
    city            = customer_db.Column(customer_db.String(100), nullable=True)
    state           = customer_db.Column(customer_db.String(100), nullable=True)
    pincode         = customer_db.Column(customer_db.String(10),  nullable=True)
    country         = customer_db.Column(customer_db.String(100), nullable=False, default="India")
    gst_number      = customer_db.Column(customer_db.String(20),  nullable=True)
    pan_number      = customer_db.Column(customer_db.String(15),  nullable=True)
    gst_type        = customer_db.Column(customer_db.String(30),  nullable=False, default="Regular")
    credit_limit    = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    credit_days     = customer_db.Column(customer_db.Integer,     nullable=False, default=30)
    pending         = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    last_payment    = customer_db.Column(customer_db.Date,        nullable=True)
    opening_balance = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    status          = customer_db.Column(customer_db.String(50),  nullable=False, default="Active")
    notes           = customer_db.Column(customer_db.Text,        nullable=True)
    created_at      = customer_db.Column(customer_db.Date,        nullable=False, default=date.today)

    def __repr__(self):
        return f"<Client {self.id} – {self.name}>"

class Supplier(customer_db.Model):
    __tablename__ = "suppliers"
 
    id              = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    company_id      = customer_db.Column(customer_db.String(20),  nullable=False)
    name            = customer_db.Column(customer_db.String(200), nullable=False)
    supplier_type   = customer_db.Column(customer_db.String(30),  nullable=False, default="Business")  # Business / Individual
    contact_person  = customer_db.Column(customer_db.String(150), nullable=True)
    phone           = customer_db.Column(customer_db.String(20),  nullable=True)
    alternate_phone = customer_db.Column(customer_db.String(20),  nullable=True)
    email           = customer_db.Column(customer_db.String(255), nullable=True)
    website         = customer_db.Column(customer_db.String(255), nullable=True)
    address_line1   = customer_db.Column(customer_db.String(300), nullable=True)
    address_line2   = customer_db.Column(customer_db.String(300), nullable=True)
    city            = customer_db.Column(customer_db.String(100), nullable=True)
    state           = customer_db.Column(customer_db.String(100), nullable=True)
    pincode         = customer_db.Column(customer_db.String(10),  nullable=True)
    country         = customer_db.Column(customer_db.String(100), nullable=False, default="India")
    gst_number      = customer_db.Column(customer_db.String(20),  nullable=True)
    pan_number      = customer_db.Column(customer_db.String(15),  nullable=True)
    gst_type        = customer_db.Column(customer_db.String(30),  nullable=False, default="Regular")   # Regular / Composition / Unregistered
    credit_limit    = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)   # max credit supplier gives us
    credit_days     = customer_db.Column(customer_db.Integer,     nullable=False, default=30)
    payable         = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)   # amount WE owe supplier
    opening_balance = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    last_purchase   = customer_db.Column(customer_db.Date,        nullable=True)
    status          = customer_db.Column(customer_db.String(50),  nullable=False, default="Active")    # Active / Inactive / Blacklisted
    notes           = customer_db.Column(customer_db.Text,        nullable=True)
    created_at      = customer_db.Column(customer_db.Date,        nullable=False, default=date.today)

    brands = customer_db.relationship("SupplierBrand", back_populates="supplier", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Supplier {self.id} – {self.name}>"


# ── 5b. Supplier Brands (courier tie-ups under one supplier, e.g. IMD → Bluedart, DPD, DHL) ──
class SupplierBrand(customer_db.Model):
    __tablename__ = "supplier_brands"

    id          = customer_db.Column(customer_db.Integer, primary_key=True, autoincrement=True)
    supplier_id = customer_db.Column(customer_db.Integer, customer_db.ForeignKey("suppliers.id"), nullable=False)
    brand_name  = customer_db.Column(customer_db.String(100), nullable=False)
    created_at  = customer_db.Column(customer_db.Date, nullable=False, default=date.today)

    supplier = customer_db.relationship("Supplier", back_populates="brands")

    def __repr__(self):
        return f"<SupplierBrand {self.brand_name} (supplier {self.supplier_id})>"


# ── 6. Orders ─────────────────────────────────────────────────────────────────
class Order(customer_db.Model):
    __tablename__ = "orders"

    id          = customer_db.Column(customer_db.Integer,    primary_key=True, autoincrement=True)
    order_id    = customer_db.Column(customer_db.String(30), unique=True, nullable=False)
    company_id  = customer_db.Column(customer_db.String(20), nullable=False)
    client_id   = customer_db.Column(customer_db.Integer,   nullable=True)
    employee_id = customer_db.Column(customer_db.String(20), nullable=True)
    date        = customer_db.Column(customer_db.Date,       nullable=False, default=date.today)
    amount      = customer_db.Column(customer_db.Float,      nullable=False, default=0.0)
    received    = customer_db.Column(customer_db.Float,      nullable=False, default=0.0)
    status      = customer_db.Column(customer_db.String(50), nullable=False, default="Pending")

    def __repr__(self):
        return f"<Order {self.order_id}>"


# ── 7. Stock Items ────────────────────────────────────────────────────────────
class StockItem(customer_db.Model):
    __tablename__ = "stock_items"

    id                 = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    company_id         = customer_db.Column(customer_db.String(20),  nullable=False)
    code               = customer_db.Column(customer_db.String(50),  nullable=False)
    name               = customer_db.Column(customer_db.String(200), nullable=False)
    category           = customer_db.Column(customer_db.String(100), nullable=True)
    quantity           = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    unit               = customer_db.Column(customer_db.String(20),  nullable=True, default="pcs")
    unit_price         = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    reorder_level      = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    hsn                = customer_db.Column(customer_db.String(20),  nullable=True)
    last_updated       = customer_db.Column(customer_db.Date,        nullable=True)
    purchase_rate      = customer_db.Column(customer_db.Float,       nullable=True)
    last_purchase_rate = customer_db.Column(customer_db.Float,       nullable=True)
    avg_purchase_rate  = customer_db.Column(customer_db.Float,       nullable=True)
    gst_percent        = customer_db.Column(customer_db.Float,       nullable=True, default=18.0)
    selling_price      = customer_db.Column(customer_db.Float,       nullable=True)
    margin_percent     = customer_db.Column(customer_db.Float,       nullable=True)
    client_id          = customer_db.Column(customer_db.Integer,     nullable=True, default=None)
    item_type          = customer_db.Column(customer_db.String(50),  nullable=True, default=None)

    def __repr__(self):
        return f"<StockItem {self.code} – {self.name}>"


# ── 8. Invoices ───────────────────────────────────────────────────────────────
class Invoice(customer_db.Model):
    __tablename__ = "invoices"

    id             = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    invoice_id     = customer_db.Column(customer_db.String(30),  unique=True, nullable=False)
    company_id     = customer_db.Column(customer_db.String(20),  nullable=False)
    client_id      = customer_db.Column(customer_db.Integer,     nullable=True)
    date           = customer_db.Column(customer_db.Date,        nullable=False, default=date.today)
    due_date       = customer_db.Column(customer_db.Date,        nullable=True)
    status         = customer_db.Column(customer_db.String(50),  nullable=False, default="Pending")
    subtotal       = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    tax_amount     = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    grand_total    = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    contact_person = customer_db.Column(customer_db.String(150), nullable=True)
    email          = customer_db.Column(customer_db.String(255), nullable=True)
    phone          = customer_db.Column(customer_db.String(20),  nullable=True)
    terms          = customer_db.Column(customer_db.Text,        nullable=True)
    paid_amount    = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    balance        = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    created_at     = customer_db.Column(customer_db.DateTime,    nullable=False, default=datetime.utcnow)
    resale_charges   = customer_db.Column(customer_db.Float,     nullable=False, default=0.0)
    resale_reason    = customer_db.Column(customer_db.String(200), nullable=True)
    resale_date      = customer_db.Column(customer_db.Date,      nullable=True)
    resale_notes     = customer_db.Column(customer_db.Text,      nullable=True)
    has_resale       = customer_db.Column(customer_db.Boolean,   nullable=False, default=False)

    items = customer_db.relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Invoice {self.invoice_id}>"
    
    @property
    def client_obj(self):
        """Helper to get client object"""
        from sqlalchemy.orm import object_session
        session = object_session(self)
        if session:
            return session.query(Client).filter_by(id=self.client_id).first()
        return None

# ── 19. Price Lists (Shipping Rates) ─────────────────────────────────────────
class PriceList(customer_db.Model):
    __tablename__ = "price_lists"

    id          = customer_db.Column(customer_db.Integer, primary_key=True, autoincrement=True)
    company_id  = customer_db.Column(customer_db.String(20), nullable=False)
    courier     = customer_db.Column(customer_db.String(50), nullable=False)
    filename    = customer_db.Column(customer_db.String(255), nullable=False)
    file_path   = customer_db.Column(customer_db.String(500), nullable=False)
    rate_data   = customer_db.Column(customer_db.Text, nullable=True)
    is_active   = customer_db.Column(customer_db.Boolean, default=True)
    list_type   = customer_db.Column(customer_db.String(20), nullable=False, default='sales')  
    uploaded_at = customer_db.Column(customer_db.DateTime, nullable=False, default=datetime.utcnow)
    uploaded_by = customer_db.Column(customer_db.String(100), nullable=True)

    def __repr__(self):
        return f"<PriceList {self.courier} - {self.filename}>"


# ── 20. Rate Lookup Cache ────────────────────────────────────────────────────
class RateLookup(customer_db.Model):
    __tablename__ = "rate_lookups"

    id          = customer_db.Column(customer_db.Integer, primary_key=True, autoincrement=True)
    company_id  = customer_db.Column(customer_db.String(20), nullable=False)
    courier     = customer_db.Column(customer_db.String(50), nullable=False)
    destination = customer_db.Column(customer_db.String(100), nullable=False)
    weight      = customer_db.Column(customer_db.Float, nullable=False)
    rate        = customer_db.Column(customer_db.Float, nullable=False)
    created_at  = customer_db.Column(customer_db.DateTime, nullable=False, default=datetime.utcnow)
    lookup_count = customer_db.Column(customer_db.Integer, default=1)  # Track usage

    
# ── 8a. Invoice Line Items ────────────────────────────────────────────────────
class InvoiceItem(customer_db.Model):
    __tablename__ = "invoice_items"

    id            = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    invoice_id    = customer_db.Column(customer_db.Integer,     customer_db.ForeignKey("invoices.id"), nullable=False)
    stock_item_id = customer_db.Column(customer_db.Integer,     nullable=True)
    code          = customer_db.Column(customer_db.String(50),  nullable=True)
    description   = customer_db.Column(customer_db.String(300), nullable=False)
    qty           = customer_db.Column(customer_db.Float,       nullable=False, default=1.0)
    rate          = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    discount      = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)

    invoice = customer_db.relationship("Invoice", back_populates="items")

    def __repr__(self):
        return f"<InvoiceItem {self.id}>"


# ── 9. Estimates ──────────────────────────────────────────────────────────────
class Estimate(customer_db.Model):
    __tablename__ = "estimates"

    id           = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    estimate_id  = customer_db.Column(customer_db.String(30),  unique=True, nullable=False)
    company_id   = customer_db.Column(customer_db.String(20),  nullable=False)
    client_id    = customer_db.Column(customer_db.Integer,     nullable=True)
    date         = customer_db.Column(customer_db.Date,        nullable=False, default=date.today)
    valid_until  = customer_db.Column(customer_db.Date,        nullable=True)
    status       = customer_db.Column(customer_db.String(50),  nullable=False, default="Draft")
    subtotal     = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    tax_amount   = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    grand_total  = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    notes        = customer_db.Column(customer_db.Text,        nullable=True)
    created_at   = customer_db.Column(customer_db.DateTime,    nullable=False, default=datetime.utcnow)
    contact_person = customer_db.Column(customer_db.String(150), nullable=True)
    email          = customer_db.Column(customer_db.String(150), nullable=True)
    phone          = customer_db.Column(customer_db.String(30),  nullable=True)
    terms          = customer_db.Column(customer_db.Text,        nullable=True)

    items = customer_db.relationship("EstimateItem", back_populates="estimate", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Estimate {self.estimate_id}>"
    
    @property
    def client_obj(self):
        """Helper to get client object"""
        from sqlalchemy.orm import object_session
        session = object_session(self)
        if session:
            return session.query(Client).filter_by(id=self.client_id).first()
        return None


class EstimateItem(customer_db.Model):
    __tablename__ = "estimate_items"

    id            = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    estimate_id   = customer_db.Column(customer_db.Integer,     customer_db.ForeignKey("estimates.id"), nullable=False)
    stock_item_id = customer_db.Column(customer_db.Integer,     nullable=True)
    code          = customer_db.Column(customer_db.String(50),  nullable=True)
    description   = customer_db.Column(customer_db.String(300), nullable=False)
    qty           = customer_db.Column(customer_db.Float,       nullable=False, default=1.0)
    rate          = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    discount      = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)

    estimate = customer_db.relationship("Estimate", back_populates="items")

    def __repr__(self):
        return f"<EstimateItem {self.id}>"


# ── 10. Purchase Invoices ─────────────────────────────────────────────────────
class PurchaseInvoice(customer_db.Model):
    __tablename__ = "purchase_invoices"

    id             = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    invoice_id     = customer_db.Column(customer_db.String(30),  unique=True, nullable=False)
    company_id     = customer_db.Column(customer_db.String(20),  nullable=False)
    supplier_id    = customer_db.Column(customer_db.Integer,     nullable=True)
    supplier_name  = customer_db.Column(customer_db.String(200), nullable=True)
    invoice_number = customer_db.Column(customer_db.String(100), nullable=True)
    date           = customer_db.Column(customer_db.Date,        nullable=False, default=date.today)
    due_date       = customer_db.Column(customer_db.Date,        nullable=True)
    subtotal       = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    tax_amount     = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    grand_total    = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    paid_amount    = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    balance        = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    status         = customer_db.Column(customer_db.String(50),  nullable=False, default="Pending")
    payment_terms  = customer_db.Column(customer_db.String(100), nullable=True)   # ← ADDED: was causing flush() crash
    notes          = customer_db.Column(customer_db.Text,        nullable=True)
    file_path      = customer_db.Column(customer_db.String(500), nullable=True)
    ocr_data       = customer_db.Column(customer_db.Text,        nullable=True)
    created_at     = customer_db.Column(customer_db.DateTime,    nullable=False, default=datetime.utcnow)

    items            = customer_db.relationship("PurchaseInvoiceItem",  back_populates="purchase_invoice", cascade="all, delete-orphan")
    purchase_history = customer_db.relationship("StockPurchaseHistory", back_populates="purchase_invoice", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<PurchaseInvoice {self.invoice_id}>"
    
    @property
    def supplier(self):
        """Helper to get supplier object"""
        from sqlalchemy.orm import object_session
        session = object_session(self)
        if session:
            return session.query(Supplier).filter_by(id=self.supplier_id).first()
        return None


class PurchaseInvoiceItem(customer_db.Model):
    __tablename__ = "purchase_invoice_items"

    id                  = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    purchase_invoice_id = customer_db.Column(customer_db.Integer,     customer_db.ForeignKey("purchase_invoices.id"), nullable=False)
    stock_item_id       = customer_db.Column(customer_db.Integer,     nullable=True)
    code                = customer_db.Column(customer_db.String(50),  nullable=True)
    description         = customer_db.Column(customer_db.String(300), nullable=False)
    hsn                 = customer_db.Column(customer_db.String(20),  nullable=True)
    quantity            = customer_db.Column(customer_db.Float,       nullable=False, default=1.0)
    unit                = customer_db.Column(customer_db.String(20),  nullable=True, default="pcs")
    purchase_rate       = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    discount_percent    = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    taxable_value       = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    gst_percent         = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    cgst_amount         = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    sgst_amount         = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    igst_amount         = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    total_amount        = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)

    # ── Logistics-specific particulars (added) ───────────────────────────────
    docket_no       = customer_db.Column(customer_db.String(100), nullable=True)   # AWB number
    party_name      = customer_db.Column(customer_db.String(200), nullable=True)   # client tied to that AWB
    destination     = customer_db.Column(customer_db.String(150), nullable=True)
    courier_name    = customer_db.Column(customer_db.String(100), nullable=True)   # Bluedart, DHL, DPD...
    weight_kg       = customer_db.Column(customer_db.Float,       nullable=True, default=0.0)
    rate_per_kg     = customer_db.Column(customer_db.Float,       nullable=True, default=0.0)

    purchase_invoice = customer_db.relationship("PurchaseInvoice", back_populates="items")

class PurchasePayment(customer_db.Model):
    __tablename__ = "purchase_payments"

    id             = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    company_id     = customer_db.Column(customer_db.String(20),  nullable=False)
    invoice_id     = customer_db.Column(customer_db.Integer,     customer_db.ForeignKey("purchase_invoices.id"), nullable=False)
    supplier_id    = customer_db.Column(customer_db.Integer,     nullable=True)
    date           = customer_db.Column(customer_db.Date,        nullable=False, default=date.today)
    amount         = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    pay_mode       = customer_db.Column(customer_db.String(30),  nullable=False, default="Cash")
    narration      = customer_db.Column(customer_db.String(300), nullable=True)
    created_at     = customer_db.Column(customer_db.DateTime,    nullable=False, default=datetime.utcnow)
    created_by     = customer_db.Column(customer_db.String(50),  nullable=True)

    invoice = customer_db.relationship("PurchaseInvoice", backref="payments")
# ── 11. Stock Purchase History ────────────────────────────────────────────────
class StockPurchaseHistory(customer_db.Model):
    __tablename__ = "stock_purchase_history"

    id                  = customer_db.Column(customer_db.Integer,  primary_key=True, autoincrement=True)
    stock_item_id       = customer_db.Column(customer_db.Integer,  nullable=False)
    purchase_invoice_id = customer_db.Column(customer_db.Integer,
                              customer_db.ForeignKey("purchase_invoices.id"), nullable=True)
    quantity            = customer_db.Column(customer_db.Float,    nullable=False)
    purchase_rate       = customer_db.Column(customer_db.Float,    nullable=False)
    gst_percent         = customer_db.Column(customer_db.Float,    nullable=False, default=0.0)
    purchase_date       = customer_db.Column(customer_db.Date,     nullable=False, default=date.today)
    movement_type       = customer_db.Column(customer_db.String(10), nullable=True, default="IN")
    reference           = customer_db.Column(customer_db.String(100), nullable=True)

    purchase_invoice = customer_db.relationship("PurchaseInvoice", back_populates="purchase_history")


# ── 12. Cash Transactions ─────────────────────────────────────────────────────
class CashTransaction(customer_db.Model):
    __tablename__ = "cash_transactions"

    id          = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    company_id  = customer_db.Column(customer_db.String(20),  nullable=False)
    type        = customer_db.Column(customer_db.String(20),  nullable=False)
    date        = customer_db.Column(customer_db.Date,        nullable=False, default=date.today)
    category    = customer_db.Column(customer_db.String(100), nullable=False)
    description = customer_db.Column(customer_db.String(300), nullable=False)
    amount      = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    reference   = customer_db.Column(customer_db.String(100), nullable=True)
    notes       = customer_db.Column(customer_db.Text,        nullable=True)
    created_at  = customer_db.Column(customer_db.DateTime,    nullable=False, default=datetime.utcnow)
    created_by  = customer_db.Column(customer_db.String(50),  nullable=True)


# ── 13. Bank Accounts ─────────────────────────────────────────────────────────
class BankAccount(customer_db.Model):
    __tablename__ = "bank_accounts"

    id             = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    company_id     = customer_db.Column(customer_db.String(20),  nullable=False)
    bank_name      = customer_db.Column(customer_db.String(200), nullable=False)
    account_name   = customer_db.Column(customer_db.String(200), nullable=False)
    account_number = customer_db.Column(customer_db.String(50),  nullable=False, unique=True)
    ifsc_code      = customer_db.Column(customer_db.String(20),  nullable=True)
    branch         = customer_db.Column(customer_db.String(200), nullable=True)
    balance        = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    opening_balance= customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    status         = customer_db.Column(customer_db.String(30),  nullable=False, default="Active")
    notes          = customer_db.Column(customer_db.Text,        nullable=True)
    created_at     = customer_db.Column(customer_db.DateTime,    nullable=False, default=datetime.utcnow)
    updated_at     = customer_db.Column(customer_db.DateTime,    nullable=True, onupdate=datetime.utcnow)

    transactions = customer_db.relationship("BankTransaction", back_populates="bank_account", cascade="all, delete-orphan")


# ── 14. Bank Transactions ─────────────────────────────────────────────────────
class BankTransaction(customer_db.Model):
    __tablename__ = "bank_transactions"

    id               = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    bank_account_id  = customer_db.Column(customer_db.Integer,     customer_db.ForeignKey("bank_accounts.id"), nullable=False)
    company_id       = customer_db.Column(customer_db.String(20),  nullable=False)
    type             = customer_db.Column(customer_db.String(20),  nullable=False)
    date             = customer_db.Column(customer_db.Date,        nullable=False, default=date.today)
    description      = customer_db.Column(customer_db.String(300), nullable=False)
    amount           = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    reference        = customer_db.Column(customer_db.String(100), nullable=True)
    transaction_mode = customer_db.Column(customer_db.String(30),  nullable=True)
    notes            = customer_db.Column(customer_db.Text,        nullable=True)
    created_at       = customer_db.Column(customer_db.DateTime,    nullable=False, default=datetime.utcnow)
    created_by       = customer_db.Column(customer_db.String(50),  nullable=True)

    bank_account = customer_db.relationship("BankAccount", back_populates="transactions")


# ── 15. Loans ─────────────────────────────────────────────────────────────────
class Loan(customer_db.Model):
    __tablename__ = "loans"

    id            = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    company_id    = customer_db.Column(customer_db.String(20),  nullable=False)
    type          = customer_db.Column(customer_db.String(20),  nullable=False)
    party_name    = customer_db.Column(customer_db.String(200), nullable=False)
    loan_date     = customer_db.Column(customer_db.Date,        nullable=False, default=date.today)
    amount        = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    interest_rate = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    tenure        = customer_db.Column(customer_db.Integer,     nullable=False, default=12)
    emi_amount    = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    purpose       = customer_db.Column(customer_db.String(300), nullable=True)
    notes         = customer_db.Column(customer_db.Text,        nullable=True)
    status        = customer_db.Column(customer_db.String(30),  nullable=False, default="Active")
    created_at    = customer_db.Column(customer_db.DateTime,    nullable=False, default=datetime.utcnow)
    created_by    = customer_db.Column(customer_db.String(50),  nullable=True)

    repayments = customer_db.relationship("LoanRepayment", back_populates="loan", cascade="all, delete-orphan")

    @property
    def repaid_amount(self):
        return sum(r.amount for r in self.repayments)

    @property
    def remaining_amount(self):
        return max(0, self.amount - self.repaid_amount)
    
    @property
    def repayment_percentage(self):
        if self.amount > 0:
            return (self.repaid_amount / self.amount) * 100
        return 0


class LoanRepayment(customer_db.Model):
    __tablename__ = "loan_repayments"

    id           = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    loan_id      = customer_db.Column(customer_db.Integer,     customer_db.ForeignKey("loans.id"), nullable=False)
    date         = customer_db.Column(customer_db.Date,        nullable=False, default=date.today)
    amount       = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    payment_mode = customer_db.Column(customer_db.String(30),  nullable=False, default="Cash")
    reference    = customer_db.Column(customer_db.String(100), nullable=True)
    notes        = customer_db.Column(customer_db.Text,        nullable=True)
    created_at   = customer_db.Column(customer_db.DateTime,    nullable=False, default=datetime.utcnow)

    loan = customer_db.relationship("Loan", back_populates="repayments")


# ── 15b. Cheques ───────────────────────────────────────────────────────────────
# Register of cheques received from clients or issued to suppliers.
# A cheque sits in "Pending" status until it actually clears the bank; only
# clearing creates the real BankTransaction that moves the bank balance.
class Cheque(customer_db.Model):
    __tablename__ = "cheques"

    id              = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    company_id      = customer_db.Column(customer_db.String(20),  nullable=False)
    direction       = customer_db.Column(customer_db.String(10),  nullable=False)   # 'received' | 'paid'
    party_type      = customer_db.Column(customer_db.String(10),  nullable=True)    # 'client' | 'supplier'
    party_id        = customer_db.Column(customer_db.Integer,     nullable=True)
    party_name      = customer_db.Column(customer_db.String(200), nullable=False)
    cheque_no       = customer_db.Column(customer_db.String(30),  nullable=False)
    cheque_date     = customer_db.Column(customer_db.Date,        nullable=False, default=date.today)
    bank_name       = customer_db.Column(customer_db.String(200), nullable=True)
    bank_account_id = customer_db.Column(customer_db.Integer,     customer_db.ForeignKey("bank_accounts.id"), nullable=True)
    amount          = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    narration       = customer_db.Column(customer_db.String(300), nullable=True)
    status          = customer_db.Column(customer_db.String(20),  nullable=False, default="Pending")  # Pending | Cleared | Bounced | Cancelled
    cleared_date    = customer_db.Column(customer_db.Date,        nullable=True)
    bank_txn_id     = customer_db.Column(customer_db.Integer,     customer_db.ForeignKey("bank_transactions.id"), nullable=True)
    notes           = customer_db.Column(customer_db.Text,        nullable=True)
    created_at      = customer_db.Column(customer_db.DateTime,    nullable=False, default=datetime.utcnow)
    created_by      = customer_db.Column(customer_db.String(50),  nullable=True)

    bank_account = customer_db.relationship("BankAccount")


# ── 16. Company Manifest ──────────────────────────────────────────────────────
# Tracks boxes received from a shipper client and how they are distributed
# to different courier companies. Saving a manifest DEDUCTS stock from StockItem.
class CompanyManifest(customer_db.Model):
    __tablename__ = "company_manifests"

    id             = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    manifest_id    = customer_db.Column(customer_db.String(30),  unique=True, nullable=False)
    company_id     = customer_db.Column(customer_db.String(20),  nullable=False)
    date           = customer_db.Column(customer_db.Date,        nullable=False, default=date.today)
    # shipper = the customer who brought boxes in (links to Client.id)
    shipper_client_id   = customer_db.Column(customer_db.Integer, nullable=False)
    shipper_client_name = customer_db.Column(customer_db.String(200), nullable=False)
    # stock item whose qty is deducted (box/parcel stock)
    stock_item_id  = customer_db.Column(customer_db.Integer,     nullable=True)
    total_boxes    = customer_db.Column(customer_db.Integer,     nullable=False, default=0)
    notes          = customer_db.Column(customer_db.Text,        nullable=True)
    created_at     = customer_db.Column(customer_db.DateTime,    nullable=False, default=datetime.utcnow)
    created_by     = customer_db.Column(customer_db.String(50),  nullable=True)

    entries = customer_db.relationship(
        "ManifestEntry", back_populates="manifest", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<CompanyManifest {self.manifest_id}>"


# ── 17. Manifest Entry (courier allocation per manifest) ──────────────────────
class ManifestEntry(customer_db.Model):
    __tablename__ = "manifest_entries"

    id            = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    manifest_id   = customer_db.Column(customer_db.Integer,
                        customer_db.ForeignKey("company_manifests.id"), nullable=False)
    courier_name  = customer_db.Column(customer_db.String(200), nullable=False)
    boxes         = customer_db.Column(customer_db.Integer,     nullable=False, default=0)
    docket_no     = customer_db.Column(customer_db.String(100), nullable=True)
    docket_id     = customer_db.Column(customer_db.Integer,     nullable=True)   # ← ADD
    stock_item_id = customer_db.Column(customer_db.Integer,     nullable=True)
    stock_item_name = customer_db.Column(customer_db.String(200), nullable=True) # ← ADD
    notes         = customer_db.Column(customer_db.Text,        nullable=True)
    item_type = customer_db.Column(customer_db.String(50), nullable=True)

    manifest = customer_db.relationship("CompanyManifest", back_populates="entries")
    

    def __repr__(self):
        return f"<ManifestEntry {self.courier_name} x{self.boxes}>"


# Expenses
# ── 18. Daily Expenses ────────────────────────────────────────────────────────
class Expense(customer_db.Model):
    __tablename__ = "expenses"

    id          = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    company_id  = customer_db.Column(customer_db.String(20),  nullable=False)
    date        = customer_db.Column(customer_db.Date,        nullable=False, default=date.today)
    category    = customer_db.Column(customer_db.String(100), nullable=False)
    description = customer_db.Column(customer_db.String(300), nullable=True)
    amount      = customer_db.Column(customer_db.Float,       nullable=False, default=0.0)
    payment_mode= customer_db.Column(customer_db.String(30),  nullable=False, default="Cash")
    reference   = customer_db.Column(customer_db.String(100), nullable=True)
    created_by  = customer_db.Column(customer_db.String(100), nullable=True)
    created_at  = customer_db.Column(customer_db.DateTime,    nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<Expense {self.id} {self.category} ₹{self.amount}>"


# ── 19. WhatsApp Send Log ──────────────────────────────────────────────────────
# One row per attempted send — transactional (invoice_id set) or campaign
# (campaign_id set). Lives in the customer DB because volume scales with the
# tenant's own message traffic, same tier as Expense/CashTransaction.
class WhatsAppLog(customer_db.Model):
    __tablename__ = "whatsapp_logs"

    id             = customer_db.Column(customer_db.Integer,     primary_key=True, autoincrement=True)
    company_id     = customer_db.Column(customer_db.String(20),  nullable=False)
    template_key   = customer_db.Column(customer_db.String(50),  nullable=True)
    to_phone       = customer_db.Column(customer_db.String(20),  nullable=False)
    invoice_id     = customer_db.Column(customer_db.String(30),  nullable=True)  # set for transactional sends
    manifest_id    = customer_db.Column(customer_db.String(30),  nullable=True)  # set for manifest/AWB sends
    campaign_id    = customer_db.Column(customer_db.String(50),  nullable=True)  # set for bulk campaign sends
    status         = customer_db.Column(customer_db.String(20),  nullable=False, default="pending")  # pending|sent|failed|manual_pending
    provider       = customer_db.Column(customer_db.String(20),  nullable=True)
    provider_msg_id= customer_db.Column(customer_db.String(100), nullable=True)
    error_message  = customer_db.Column(customer_db.Text,        nullable=True)
    attempt_count  = customer_db.Column(customer_db.Integer,     nullable=False, default=0)
    manual_link    = customer_db.Column(customer_db.Text,        nullable=True)  # wa.me link when no API / send failed
    created_at     = customer_db.Column(customer_db.DateTime,    nullable=False, default=datetime.utcnow)
    sent_at        = customer_db.Column(customer_db.DateTime,    nullable=True)

    def __repr__(self):
        return f"<WhatsAppLog {self.id} {self.to_phone} {self.status}>"
