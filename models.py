

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date

db = SQLAlchemy()


# ── 1. Subscription Plans ────────────────────────────────────────────────────
class SubscriptionPlan(db.Model):
    __tablename__ = "subscription_plans"

    id              = db.Column(db.String(20),  primary_key=True)          # 'basic','premium','gold','custom'
    name            = db.Column(db.String(100), nullable=False)
    price           = db.Column(db.String(50),  nullable=False)            # stored as string to allow "Contact Sales"
    max_companies   = db.Column(db.String(20),  nullable=False)            # int or "Unlimited"
    max_users       = db.Column(db.String(20),  nullable=False)            # int or "Unlimited"
    features        = db.Column(db.Text,        nullable=True)             # comma-separated list

    # relationships
    companies       = db.relationship("Company",        back_populates="plan_obj")
    registered_users = db.relationship("RegisteredUser", back_populates="plan_obj")

    def __repr__(self):
        return f"<SubscriptionPlan {self.id}>"


# ── 2. Registered Users (account / subscription holders) ────────────────────
class RegisteredUser(db.Model):
    __tablename__ = "registered_users"

    id                = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    user_id           = db.Column(db.String(20),  unique=True, nullable=False)   # USR001 …
    email             = db.Column(db.String(255), unique=True, nullable=False)
    password_hash     = db.Column(db.String(255), nullable=False)
    full_name         = db.Column(db.String(150), nullable=False)
    phone             = db.Column(db.String(20),  nullable=True)
    role              = db.Column(db.String(50),  nullable=False, default="owner")  # super_admin / owner
    subscription_plan = db.Column(db.String(20),  db.ForeignKey("subscription_plans.id"), nullable=True)
    created_at        = db.Column(db.Date,        nullable=False, default=date.today)
    is_active         = db.Column(db.Boolean,     nullable=False, default=True)

    # relationships
    plan_obj  = db.relationship("SubscriptionPlan", back_populates="registered_users")
    companies = db.relationship("Company", back_populates="owner",
                                foreign_keys="Company.owner_email",
                                primaryjoin="RegisteredUser.email == Company.owner_email")

    def __repr__(self):
        return f"<RegisteredUser {self.email}>"


# ── 3. Companies ─────────────────────────────────────────────────────────────
class Company(db.Model):
    __tablename__ = "companies"

    id                    = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    company_id            = db.Column(db.String(20),  unique=True, nullable=False)   # COMP001 …
    company_name          = db.Column(db.String(200), nullable=False)
    owner_email           = db.Column(db.String(255), db.ForeignKey("registered_users.email"), nullable=False)
    subscription_plan     = db.Column(db.String(20),  db.ForeignKey("subscription_plans.id"), nullable=True)
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

    # relationships
    owner        = db.relationship("RegisteredUser", back_populates="companies",
                                   foreign_keys=[owner_email])
    plan_obj     = db.relationship("SubscriptionPlan", back_populates="companies")
    company_users = db.relationship("CompanyUser",  back_populates="company", cascade="all, delete-orphan")
    orders       = db.relationship("Order",         back_populates="company", cascade="all, delete-orphan")
    clients      = db.relationship("Client",        back_populates="company", cascade="all, delete-orphan")
    stock_items  = db.relationship("StockItem",     back_populates="company", cascade="all, delete-orphan")
    invoices     = db.relationship("Invoice",       back_populates="company", cascade="all, delete-orphan")
    estimates    = db.relationship("Estimate",      back_populates="company", cascade="all, delete-orphan")
    purchase_invoices   = db.relationship("PurchaseInvoice",   back_populates="company", cascade="all, delete-orphan")
    customer_invoices   = db.relationship("CustomerInvoice",   back_populates="company", cascade="all, delete-orphan")
    shipper_invoices    = db.relationship("ShipperInvoice",    back_populates="company", cascade="all, delete-orphan")

    @property
    def user_count(self):
        return len(self.company_users)

    @property
    def max_users(self):
        v = self.max_users_per_company
        if v is None:
            return 999
        try:
            return int(v)
        except (ValueError, TypeError):
            return 999

    def __repr__(self):
        return f"<Company {self.company_id} – {self.company_name}>"


# ── 4. Company Users (employees within a company) ────────────────────────────
class CompanyUser(db.Model):
    __tablename__ = "company_users"

    id            = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    user_id       = db.Column(db.String(20),  unique=True, nullable=False)  # EMP001 …
    company_id    = db.Column(db.String(20),  db.ForeignKey("companies.company_id"), nullable=False)
    email         = db.Column(db.String(255), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name     = db.Column(db.String(150), nullable=False)
    role          = db.Column(db.String(50),  nullable=False, default="employee")
    department    = db.Column(db.String(100), nullable=True)
    phone         = db.Column(db.String(20),  nullable=True)
    is_active     = db.Column(db.Boolean,     nullable=False, default=True)
    created_at    = db.Column(db.Date,        nullable=False, default=date.today)

    # relationships
    company = db.relationship("Company", back_populates="company_users")
    orders  = db.relationship("Order",   back_populates="employee")

    def __repr__(self):
        return f"<CompanyUser {self.user_id} – {self.email}>"


# ── 5. Clients ────────────────────────────────────────────────────────────────
class Client(db.Model):
    __tablename__ = "clients"

    id               = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    company_id       = db.Column(db.String(20),  db.ForeignKey("companies.company_id"), nullable=False)

    # ── Core identity ────────────────────────────────────────────────────────
    name             = db.Column(db.String(200), nullable=False)
    contact_person   = db.Column(db.String(150), nullable=True)   # primary contact at the client company
    client_type      = db.Column(db.String(30),  nullable=False, default="Business")  # Business / Individual

    # ── Contact details ───────────────────────────────────────────────────────
    phone            = db.Column(db.String(20),  nullable=True)
    alternate_phone  = db.Column(db.String(20),  nullable=True)
    email            = db.Column(db.String(255), nullable=True)
    website          = db.Column(db.String(255), nullable=True)

    # ── Address ───────────────────────────────────────────────────────────────
    address_line1    = db.Column(db.String(300), nullable=True)
    address_line2    = db.Column(db.String(300), nullable=True)
    city             = db.Column(db.String(100), nullable=True)
    state            = db.Column(db.String(100), nullable=True)
    pincode          = db.Column(db.String(10),  nullable=True)
    country          = db.Column(db.String(100), nullable=False, default="India")

    # ── GST & Tax ─────────────────────────────────────────────────────────────
    gst_number       = db.Column(db.String(20),  nullable=True, unique=False)  # unique enforced per company below
    pan_number       = db.Column(db.String(15),  nullable=True)
    gst_type         = db.Column(db.String(30),  nullable=False, default="Regular")  # Regular / Composition / Unregistered / SEZ / Export

    # ── Financial ─────────────────────────────────────────────────────────────
    credit_limit     = db.Column(db.Float,       nullable=False, default=0.0)
    credit_days      = db.Column(db.Integer,     nullable=False, default=30)   # payment due in N days
    pending          = db.Column(db.Float,       nullable=False, default=0.0)  # outstanding balance
    last_payment     = db.Column(db.Date,        nullable=True)
    opening_balance  = db.Column(db.Float,       nullable=False, default=0.0)

    # ── Status & Meta ─────────────────────────────────────────────────────────
    status           = db.Column(db.String(50),  nullable=False, default="Active")  # Active / Paid / Pending / Overdue / Inactive
    notes            = db.Column(db.Text,        nullable=True)
    created_at       = db.Column(db.Date,        nullable=False, default=date.today)

    # Unique GST per company (a GST number cannot appear twice under the same company)
    __table_args__ = (
        db.UniqueConstraint("company_id", "gst_number", name="uq_client_company_gst"),
    )

    # relationships
    company   = db.relationship("Company",  back_populates="clients")
    orders    = db.relationship("Order",    back_populates="client_obj")
    invoices  = db.relationship("Invoice",  back_populates="client_obj")
    estimates = db.relationship("Estimate", back_populates="client_obj")
    purchase_invoices   = db.relationship('PurchaseInvoice',  back_populates='supplier')
    customer_invoices   = db.relationship('CustomerInvoice',  back_populates='client_obj')
    shipper_invoices    = db.relationship('ShipperInvoice',   back_populates='shipper_obj')

    def __repr__(self):
        return f"<Client {self.id} – {self.name}>"


# ── 6. Orders ─────────────────────────────────────────────────────────────────
class Order(db.Model):
    __tablename__ = "orders"

    id          = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    order_id    = db.Column(db.String(30), unique=True, nullable=False)        # ORD-2024-001
    company_id  = db.Column(db.String(20), db.ForeignKey("companies.company_id"), nullable=False)
    client_id   = db.Column(db.Integer,   db.ForeignKey("clients.id"),          nullable=True)
    employee_id = db.Column(db.String(20), db.ForeignKey("company_users.user_id"), nullable=True)
    date        = db.Column(db.Date,       nullable=False, default=date.today)
    amount      = db.Column(db.Float,      nullable=False, default=0.0)
    received    = db.Column(db.Float,      nullable=False, default=0.0)
    status      = db.Column(db.String(50), nullable=False, default="Pending")   # Pending / Processing / Delivered

    # relationships
    company    = db.relationship("Company",     back_populates="orders")
    client_obj = db.relationship("Client",      back_populates="orders")
    employee   = db.relationship("CompanyUser", back_populates="orders")

    def __repr__(self):
        return f"<Order {self.order_id}>"

# ── 10. Purchase Invoices (Bills from Suppliers) ──────────────────────────────
class PurchaseInvoice(db.Model):
    __tablename__ = "purchase_invoices"
    
    id              = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    invoice_id      = db.Column(db.String(30),  unique=True, nullable=False)     # PURCHASE-INV-2024-001
    company_id      = db.Column(db.String(20),  db.ForeignKey("companies.company_id"), nullable=False)
    supplier_id     = db.Column(db.Integer,     db.ForeignKey("clients.id"),     nullable=True)   # supplier is a client with type="Supplier"
    invoice_number  = db.Column(db.String(100), nullable=True)   # Original invoice number from supplier
    date            = db.Column(db.Date,        nullable=False, default=date.today)
    due_date        = db.Column(db.Date,        nullable=True)
    subtotal        = db.Column(db.Float,       nullable=False, default=0.0)     # Before tax
    tax_amount      = db.Column(db.Float,       nullable=False, default=0.0)     # Total GST
    grand_total     = db.Column(db.Float,       nullable=False, default=0.0)     # Final amount
    paid_amount     = db.Column(db.Float,       nullable=False, default=0.0)     # Amount paid
    balance         = db.Column(db.Float,       nullable=False, default=0.0)     # Pending to pay
    status          = db.Column(db.String(50),  nullable=False, default="Pending")  # Pending / Partial / Paid
    payment_terms   = db.Column(db.String(200), nullable=True)
    notes           = db.Column(db.Text,        nullable=True)
    file_path       = db.Column(db.String(500), nullable=True)   # Path to uploaded PDF/image
    ocr_data        = db.Column(db.Text,        nullable=True)   # Raw OCR extracted text (JSON)
    created_at      = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # relationships
    company  = db.relationship("Company", back_populates="purchase_invoices")
    supplier = db.relationship("Client", back_populates="purchase_invoices")
    items            = db.relationship("PurchaseInvoiceItem",  back_populates="purchase_invoice", cascade="all, delete-orphan")
    purchase_history = db.relationship("StockPurchaseHistory", back_populates="purchase_invoice", cascade="all, delete-orphan")
    
    # ── Convenience properties for templates ──────────────────────────────
    @property
    def purchase_id(self):
        return self.invoice_id

    @property
    def total_amount(self):
        return self.grand_total

    @property
    def amount_paid(self):
        return self.paid_amount

    def __repr__(self):
        return f"<PurchaseInvoice {self.invoice_id}>"


# ── 10a. Purchase Invoice Line Items ──────────────────────────────────────────
class PurchaseInvoiceItem(db.Model):
    __tablename__ = "purchase_invoice_items"
    
    id                 = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    purchase_invoice_id = db.Column(db.Integer,    db.ForeignKey("purchase_invoices.id"), nullable=False)
    stock_item_id      = db.Column(db.Integer,     db.ForeignKey("stock_items.id"), nullable=True)
    
    # Item details
    code               = db.Column(db.String(50),  nullable=True)      # Product code/SKU
    description        = db.Column(db.String(300), nullable=False)
    hsn                = db.Column(db.String(20),  nullable=True)
    quantity           = db.Column(db.Float,       nullable=False, default=1.0)
    unit               = db.Column(db.String(20),  nullable=True, default="pcs")
    purchase_rate      = db.Column(db.Float,       nullable=False, default=0.0)      # Unit price excluding tax
    discount_percent   = db.Column(db.Float,       nullable=False, default=0.0)
    taxable_value      = db.Column(db.Float,       nullable=False, default=0.0)      # After discount
    gst_percent        = db.Column(db.Float,       nullable=False, default=0.0)
    cgst_amount        = db.Column(db.Float,       nullable=False, default=0.0)
    sgst_amount        = db.Column(db.Float,       nullable=False, default=0.0)
    igst_amount        = db.Column(db.Float,       nullable=False, default=0.0)
    total_amount       = db.Column(db.Float,       nullable=False, default=0.0)      # Final line total
    
    # relationships
    purchase_invoice = db.relationship("PurchaseInvoice", back_populates="items")
    stock_item       = db.relationship("StockItem", back_populates="purchase_items")
    
    def __repr__(self):
        return f"<PurchaseInvoiceItem {self.id} - {self.description}>"


# ── 11. Stock Item Purchase History (to track purchase rates) ─────────────────
class StockPurchaseHistory(db.Model):
    __tablename__ = "stock_purchase_history"
    
    id                 = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    stock_item_id      = db.Column(db.Integer,     db.ForeignKey("stock_items.id"), nullable=False)
    purchase_invoice_id = db.Column(db.Integer,    db.ForeignKey("purchase_invoices.id"), nullable=False)
    quantity           = db.Column(db.Float,       nullable=False)
    purchase_rate      = db.Column(db.Float,       nullable=False)
    gst_percent        = db.Column(db.Float,       nullable=False, default=0.0)
    purchase_date      = db.Column(db.Date,        nullable=False, default=date.today)
    
    # relationships
    stock_item      = db.relationship("StockItem", back_populates="purchase_history")
    purchase_invoice = db.relationship("PurchaseInvoice", back_populates="purchase_history")
    
    def __repr__(self):
        return f"<StockPurchaseHistory {self.stock_item_id} - {self.purchase_rate}>"


# ── 7. Stock Items ────────────────────────────────────────────────────────────
class StockItem(db.Model):
    __tablename__ = "stock_items"

    id            = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    company_id    = db.Column(db.String(20),  db.ForeignKey("companies.company_id"), nullable=False)
    code          = db.Column(db.String(50),  nullable=False)
    name          = db.Column(db.String(200), nullable=False)
    category      = db.Column(db.String(100), nullable=True)
    quantity      = db.Column(db.Float,       nullable=False, default=0.0)
    unit          = db.Column(db.String(20),  nullable=True, default="pcs")
    unit_price    = db.Column(db.Float,       nullable=False, default=0.0)
    reorder_level = db.Column(db.Float,       nullable=False, default=0.0)
    hsn           = db.Column(db.String(20),  nullable=True)
    last_updated  = db.Column(db.Date,        nullable=True)
    purchase_rate = db.Column(db.Float, nullable=True)      
    last_purchase_rate = db.Column(db.Float, nullable=True) 
    avg_purchase_rate = db.Column(db.Float, nullable=True)  
    gst_percent = db.Column(db.Float, nullable=True, default=18.0)  
    selling_price = db.Column(db.Float, nullable=True)      
    margin_percent = db.Column(db.Float, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("company_id", "code", name="uq_stock_company_code"),
    )

    # relationships
    company       = db.relationship("Company",      back_populates="stock_items")
    invoice_items = db.relationship("InvoiceItem",  back_populates="stock_item")
    estimate_items = db.relationship("EstimateItem", back_populates="stock_item")
    purchase_items = db.relationship("PurchaseInvoiceItem", back_populates="stock_item")
    purchase_history = db.relationship("StockPurchaseHistory", back_populates="stock_item")
    

    def __repr__(self):
        return f"<StockItem {self.code} – {self.name}>"


# ── 8. Invoices ───────────────────────────────────────────────────────────────
class Invoice(db.Model):
    __tablename__ = "invoices"

    id             = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    invoice_id     = db.Column(db.String(30),  unique=True, nullable=False)     # INV-20240120-123
    company_id     = db.Column(db.String(20),  db.ForeignKey("companies.company_id"), nullable=False)
    client_id      = db.Column(db.Integer,     db.ForeignKey("clients.id"),     nullable=True)
    date           = db.Column(db.Date,        nullable=False, default=date.today)
    due_date       = db.Column(db.Date,        nullable=True)
    status         = db.Column(db.String(50),  nullable=False, default="Draft")  # Draft/Sent/Paid/Overdue
    subtotal       = db.Column(db.Float,       nullable=False, default=0.0)
    tax_amount     = db.Column(db.Float,       nullable=False, default=0.0)
    grand_total    = db.Column(db.Float,       nullable=False, default=0.0)
    contact_person = db.Column(db.String(150), nullable=True)
    email          = db.Column(db.String(255), nullable=True)
    phone          = db.Column(db.String(20),  nullable=True)
    terms          = db.Column(db.Text,        nullable=True)
    created_at     = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)

    # relationships
    company    = db.relationship("Company", back_populates="invoices")
    client_obj = db.relationship("Client",  back_populates="invoices")
    items      = db.relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Invoice {self.invoice_id}>"


# ── 8a. Invoice Line Items ────────────────────────────────────────────────────
class InvoiceItem(db.Model):
    __tablename__ = "invoice_items"

    id           = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    invoice_id   = db.Column(db.Integer,     db.ForeignKey("invoices.id"), nullable=False)
    stock_item_id = db.Column(db.Integer,    db.ForeignKey("stock_items.id"), nullable=True)
    code         = db.Column(db.String(50),  nullable=True)
    description  = db.Column(db.String(300), nullable=False)
    qty          = db.Column(db.Float,       nullable=False, default=1.0)
    rate         = db.Column(db.Float,       nullable=False, default=0.0)
    discount     = db.Column(db.Float,       nullable=False, default=0.0)   # percentage

    # relationships
    invoice    = db.relationship("Invoice",   back_populates="items")
    stock_item = db.relationship("StockItem", back_populates="invoice_items")

    def __repr__(self):
        return f"<InvoiceItem {self.id} – {self.description}>"


# ── 9. Estimates ──────────────────────────────────────────────────────────────
class Estimate(db.Model):
    __tablename__ = "estimates"

    id             = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    estimate_id    = db.Column(db.String(30),  unique=True, nullable=False)     # EST-20240120-123
    company_id     = db.Column(db.String(20),  db.ForeignKey("companies.company_id"), nullable=False)
    client_id      = db.Column(db.Integer,     db.ForeignKey("clients.id"),     nullable=True)
    date           = db.Column(db.Date,        nullable=False, default=date.today)
    valid_until    = db.Column(db.Date,        nullable=True)
    status         = db.Column(db.String(50),  nullable=False, default="Draft")  # Draft/Sent/Accepted/Rejected
    subtotal       = db.Column(db.Float,       nullable=False, default=0.0)
    tax_amount     = db.Column(db.Float,       nullable=False, default=0.0)
    grand_total    = db.Column(db.Float,       nullable=False, default=0.0)
    contact_person = db.Column(db.String(150), nullable=True)
    email          = db.Column(db.String(255), nullable=True)
    phone          = db.Column(db.String(20),  nullable=True)
    terms          = db.Column(db.Text,        nullable=True)
    created_at     = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)

    # relationships
    company    = db.relationship("Company", back_populates="estimates")
    client_obj = db.relationship("Client",  back_populates="estimates")
    items      = db.relationship("EstimateItem", back_populates="estimate", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Estimate {self.estimate_id}>"


# ── 9a. Estimate Line Items ───────────────────────────────────────────────────
class EstimateItem(db.Model):
    __tablename__ = "estimate_items"

    id            = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    estimate_id   = db.Column(db.Integer,     db.ForeignKey("estimates.id"), nullable=False)
    stock_item_id = db.Column(db.Integer,     db.ForeignKey("stock_items.id"), nullable=True)
    code          = db.Column(db.String(50),  nullable=True)
    description   = db.Column(db.String(300), nullable=False)
    qty           = db.Column(db.Float,       nullable=False, default=1.0)
    rate          = db.Column(db.Float,       nullable=False, default=0.0)
    discount      = db.Column(db.Float,       nullable=False, default=0.0)   # percentage

    # relationships
    estimate   = db.relationship("Estimate",  back_populates="items")
    stock_item = db.relationship("StockItem", back_populates="estimate_items")

    def __repr__(self):
        return f"<EstimateItem {self.id} – {self.description}>"


# ═════════════════════════════════════════════════════════════════════════════
# ── LOGISTICS MODELS ─────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════════

# ── 12. Customer Invoice (Logistics) ─────────────────────────────────────────
# Raised on the end-customer for a shipment.
# Automatically feeds into the Debtors ledger (client.pending is incremented).
# ─────────────────────────────────────────────────────────────────────────────
class CustomerInvoice(db.Model):
    __tablename__ = "customer_invoices"

    id                  = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    invoice_id          = db.Column(db.String(30),  unique=True, nullable=False)   # CINV-20240501-001
    company_id          = db.Column(db.String(20),  db.ForeignKey("companies.company_id"), nullable=False)
    client_id           = db.Column(db.Integer,     db.ForeignKey("clients.id"),   nullable=True)

    # ── Invoice meta ─────────────────────────────────────────────────────────
    date                = db.Column(db.Date,        nullable=False, default=date.today)
    docket_no           = db.Column(db.String(50),  nullable=True)    # AWB / tracking reference

    # ── Shipper (sender) ──────────────────────────────────────────────────────
    customer_phone      = db.Column(db.String(20),  nullable=True)
    shipper_name        = db.Column(db.String(200), nullable=True)
    shipper_address     = db.Column(db.String(400), nullable=True)

    # ── Receiver ─────────────────────────────────────────────────────────────
    receiver_name       = db.Column(db.String(200), nullable=False)
    receiver_phone      = db.Column(db.String(20),  nullable=True)
    receiver_address    = db.Column(db.String(400), nullable=True)
    destination         = db.Column(db.String(200), nullable=True)   # country / city

    # ── Shipment details ─────────────────────────────────────────────────────
    shipment_type       = db.Column(db.String(50),  nullable=True, default="NON DC")
    mode                = db.Column(db.String(30),  nullable=True, default="COURIER")
    carrier             = db.Column(db.String(100), nullable=True)
    carrier_ref         = db.Column(db.String(100), nullable=True)   # carrier tracking / AWB
    origin              = db.Column(db.String(100), nullable=True, default="India")
    pickup_date         = db.Column(db.Date,        nullable=True)
    departure_time      = db.Column(db.DateTime,    nullable=True)
    expected_delivery   = db.Column(db.Date,        nullable=True)
    comments            = db.Column(db.Text,        nullable=True)

    # ── Financials ───────────────────────────────────────────────────────────
    freight_amount      = db.Column(db.Float,       nullable=False, default=0.0)
    fuel_surcharge      = db.Column(db.Float,       nullable=False, default=0.0)
    other_charges       = db.Column(db.Float,       nullable=False, default=0.0)
    subtotal            = db.Column(db.Float,       nullable=False, default=0.0)   # freight+fuel+other
    tax_amount          = db.Column(db.Float,       nullable=False, default=0.0)   # GST 18%
    grand_total         = db.Column(db.Float,       nullable=False, default=0.0)
    amount_paid         = db.Column(db.Float,       nullable=False, default=0.0)
    balance             = db.Column(db.Float,       nullable=False, default=0.0)

    # ── Payment info ─────────────────────────────────────────────────────────
    payment_mode        = db.Column(db.String(30),  nullable=False, default="cash")
    # cash | online | cheque | credit
    upi_app             = db.Column(db.String(50),  nullable=True)    # gpay, phonepe, paytm, …
    upi_ref             = db.Column(db.String(100), nullable=True)    # UTR / transaction ref
    cheque_no           = db.Column(db.String(50),  nullable=True)
    cheque_date         = db.Column(db.Date,        nullable=True)
    cheque_bank         = db.Column(db.String(100), nullable=True)
    drawn_bank          = db.Column(db.String(100), nullable=True)

    # ── Status & meta ────────────────────────────────────────────────────────
    status              = db.Column(db.String(30),  nullable=False, default="Draft")
    # Draft | Issued | Partial | Paid
    notes               = db.Column(db.Text,        nullable=True)
    created_at          = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)
    updated_at          = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Relationships ────────────────────────────────────────────────────────
    company    = db.relationship("Company", back_populates="customer_invoices")
    client_obj = db.relationship("Client",  back_populates="customer_invoices")
    packages   = db.relationship("CustomerInvoicePackage",
                                 back_populates="customer_invoice",
                                 cascade="all, delete-orphan")

    # ── Convenience props ────────────────────────────────────────────────────
    @property
    def supplier_name(self):
        return self.client_obj.name if self.client_obj else self.shipper_name

    def __repr__(self):
        return f"<CustomerInvoice {self.invoice_id}>"


# ── 12a. Customer Invoice — Package rows ─────────────────────────────────────
class CustomerInvoicePackage(db.Model):
    __tablename__ = "customer_invoice_packages"

    id                   = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    customer_invoice_id  = db.Column(db.Integer,    db.ForeignKey("customer_invoices.id"), nullable=False)

    qty                  = db.Column(db.Integer,    nullable=False, default=1)
    piece_type           = db.Column(db.String(50), nullable=True)    # Box, Envelope, Pallet …
    description          = db.Column(db.String(300),nullable=True)
    length_cm            = db.Column(db.Float,      nullable=True)
    width_cm             = db.Column(db.Float,      nullable=True)
    height_cm            = db.Column(db.Float,      nullable=True)
    weight_kg            = db.Column(db.Float,      nullable=True)

    # ── Calculated fields (stored for reporting) ──────────────────────────────
    volume_cbm           = db.Column(db.Float,      nullable=True)    # L×W×H / 1,000,000
    volumetric_weight_kg = db.Column(db.Float,      nullable=True)    # volume_cbm × 166.67

    # relationships
    customer_invoice = db.relationship("CustomerInvoice", back_populates="packages")

    def compute_volumetrics(self):
        """Call before saving to auto-populate volume / volumetric weight."""
        if self.length_cm and self.width_cm and self.height_cm:
            cbm = (self.length_cm * self.width_cm * self.height_cm) / 1_000_000
            self.volume_cbm           = round(cbm * (self.qty or 1), 6)
            self.volumetric_weight_kg = round(cbm * 166.67 * (self.qty or 1), 3)

    def __repr__(self):
        return f"<CustomerInvoicePackage {self.id} – {self.piece_type}>"


# ── 13. Shipper Invoice ───────────────────────────────────────────────────────
# Raised on the sending agent / shipper.
# Goes into the ShipperInvoice register ONLY — never into Debtors.
# ─────────────────────────────────────────────────────────────────────────────
class ShipperInvoice(db.Model):
    __tablename__ = "shipper_invoices"

    id                  = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    invoice_id          = db.Column(db.String(30),  unique=True, nullable=False)   # SINV-20240501-001
    company_id          = db.Column(db.String(20),  db.ForeignKey("companies.company_id"), nullable=False)
    shipper_id          = db.Column(db.Integer,     db.ForeignKey("clients.id"),   nullable=True)

    # ── Invoice meta ─────────────────────────────────────────────────────────
    date                = db.Column(db.Date,        nullable=False, default=date.today)
    docket_no           = db.Column(db.String(50),  nullable=True)

    # ── Shipper (sender / agent) ──────────────────────────────────────────────
    shipper_phone       = db.Column(db.String(20),  nullable=True)
    shipper_name        = db.Column(db.String(200), nullable=True)
    shipper_address     = db.Column(db.String(400), nullable=True)

    # ── Receiver ─────────────────────────────────────────────────────────────
    receiver_name       = db.Column(db.String(200), nullable=False)
    receiver_phone      = db.Column(db.String(20),  nullable=True)
    receiver_address    = db.Column(db.String(400), nullable=True)
    destination         = db.Column(db.String(200), nullable=True)

    # ── Shipment details ─────────────────────────────────────────────────────
    shipment_type       = db.Column(db.String(50),  nullable=True, default="NON DC")
    mode                = db.Column(db.String(30),  nullable=True, default="COURIER")
    carrier             = db.Column(db.String(100), nullable=True)
    carrier_ref         = db.Column(db.String(100), nullable=True)
    origin              = db.Column(db.String(100), nullable=True, default="India")
    pickup_date         = db.Column(db.Date,        nullable=True)
    departure_time      = db.Column(db.DateTime,    nullable=True)
    expected_delivery   = db.Column(db.Date,        nullable=True)
    comments            = db.Column(db.Text,        nullable=True)

    # ── Financials ───────────────────────────────────────────────────────────
    subtotal            = db.Column(db.Float,       nullable=False, default=0.0)   # sum of all charges
    tax_amount          = db.Column(db.Float,       nullable=False, default=0.0)   # GST 18%
    grand_total         = db.Column(db.Float,       nullable=False, default=0.0)
    amount_paid         = db.Column(db.Float,       nullable=False, default=0.0)
    balance             = db.Column(db.Float,       nullable=False, default=0.0)

    # ── Payment info ─────────────────────────────────────────────────────────
    payment_mode        = db.Column(db.String(30),  nullable=False, default="cash")
    upi_app             = db.Column(db.String(50),  nullable=True)
    upi_ref             = db.Column(db.String(100), nullable=True)
    cheque_no           = db.Column(db.String(50),  nullable=True)
    cheque_date         = db.Column(db.Date,        nullable=True)
    cheque_bank         = db.Column(db.String(100), nullable=True)
    drawn_bank          = db.Column(db.String(100), nullable=True)

    # ── Status & meta ────────────────────────────────────────────────────────
    status              = db.Column(db.String(30),  nullable=False, default="Draft")
    # Draft | Issued | Partial | Paid
    notes               = db.Column(db.Text,        nullable=True)
    created_at          = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow)
    updated_at          = db.Column(db.DateTime,    nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Relationships ────────────────────────────────────────────────────────
    company     = db.relationship("Company", back_populates="shipper_invoices")
    shipper_obj = db.relationship("Client",  back_populates="shipper_invoices")
    packages    = db.relationship("ShipperInvoicePackage",
                                  back_populates="shipper_invoice",
                                  cascade="all, delete-orphan")
    charges     = db.relationship("ShipperInvoiceCharge",
                                  back_populates="shipper_invoice",
                                  cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ShipperInvoice {self.invoice_id}>"


# ── 13a. Shipper Invoice — Package rows ──────────────────────────────────────
class ShipperInvoicePackage(db.Model):
    __tablename__ = "shipper_invoice_packages"

    id                  = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    shipper_invoice_id  = db.Column(db.Integer,    db.ForeignKey("shipper_invoices.id"), nullable=False)

    qty                 = db.Column(db.Integer,    nullable=False, default=1)
    piece_type          = db.Column(db.String(50), nullable=True)
    description         = db.Column(db.String(300),nullable=True)
    length_cm           = db.Column(db.Float,      nullable=True)
    width_cm            = db.Column(db.Float,      nullable=True)
    height_cm           = db.Column(db.Float,      nullable=True)
    weight_kg           = db.Column(db.Float,      nullable=True)

    # Calculated and stored for reporting
    volume_cbm           = db.Column(db.Float,     nullable=True)
    volumetric_weight_kg = db.Column(db.Float,     nullable=True)

    # relationships
    shipper_invoice = db.relationship("ShipperInvoice", back_populates="packages")

    def compute_volumetrics(self):
        if self.length_cm and self.width_cm and self.height_cm:
            cbm = (self.length_cm * self.width_cm * self.height_cm) / 1_000_000
            self.volume_cbm           = round(cbm * (self.qty or 1), 6)
            self.volumetric_weight_kg = round(cbm * 166.67 * (self.qty or 1), 3)

    def __repr__(self):
        return f"<ShipperInvoicePackage {self.id} – {self.piece_type}>"


# ── 13b. Shipper Invoice — Charge rows ───────────────────────────────────────
# Flexible line-items: Freight, Fuel Surcharge, Handling, Customs, etc.
# ─────────────────────────────────────────────────────────────────────────────
class ShipperInvoiceCharge(db.Model):
    __tablename__ = "shipper_invoice_charges"

    id                  = db.Column(db.Integer,     primary_key=True, autoincrement=True)
    shipper_invoice_id  = db.Column(db.Integer,     db.ForeignKey("shipper_invoices.id"), nullable=False)

    description         = db.Column(db.String(200), nullable=False)   # e.g. "Freight Charges"
    amount              = db.Column(db.Float,       nullable=False, default=0.0)

    # relationships
    shipper_invoice = db.relationship("ShipperInvoice", back_populates="charges")

    def __repr__(self):
        return f"<ShipperInvoiceCharge {self.id} – {self.description}: {self.amount}>"
