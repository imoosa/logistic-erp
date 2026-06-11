"""
db_router.py
────────────
Manages per-company database connections using SQLite.

Platform DB  → SQLite file: instance/platform.db  (managed by Flask-SQLAlchemy in app.py)
Customer DB  → Separate SQLite file per company:  instance/erp_<company_id>.db

One .db file per registered company, stored in the instance/ folder.
Safe for demo/dev use. On Render free tier, files persist within a deploy
but are wiped on redeploy — acceptable for demo purposes.

Usage in routes
───────────────
    from db_router import get_customer_session, close_customer_session
    session = get_customer_session(company_id)
    users   = session.query(CompanyUser).all()
    close_customer_session(company_id)
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from customer_models import customer_db   # exposes .metadata (plain SQLAlchemy Base)

# ─────────────────────────────────────────────────────────────────────────────
# Directory where all SQLite .db files will be stored
# ─────────────────────────────────────────────────────────────────────────────
INSTANCE_DIR = os.environ.get("SQLITE_INSTANCE_DIR", "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# In-process cache:  { company_id → scoped_session factory }
# ─────────────────────────────────────────────────────────────────────────────
_engine_cache:  dict = {}
_session_cache: dict = {}


def _db_path(company_id: str) -> str:
    """Return the absolute path to the SQLite file for a company."""
    filename = f"erp_{company_id.lower()}.db"
    return os.path.abspath(os.path.join(INSTANCE_DIR, filename))


def _build_uri(company_id: str) -> str:
    """Build the sqlite:/// URI for a company's dedicated database file."""
    return f"sqlite:///{_db_path(company_id)}"


def _get_or_create(company_id: str):
    """
    Build (or return cached) scoped_session factory for a company.
    Creates the SQLite file and all customer tables on first call.
    """
    if company_id not in _engine_cache:
        uri    = _build_uri(company_id)
        engine = create_engine(
            uri,
            connect_args={"check_same_thread": False},  # required for SQLite + Flask
        )

        # Enable foreign key enforcement for this connection
        from sqlalchemy import event
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        # Create all customer tables in the new .db file
        customer_db.metadata.create_all(engine)

        factory = scoped_session(sessionmaker(bind=engine))
        _engine_cache[company_id]  = engine
        _session_cache[company_id] = factory

    return _session_cache[company_id]


def get_customer_session(company_id: str, db_session=None):
    """
    Return a SQLAlchemy session bound to this company's SQLite database.

    db_session is accepted for API compatibility but is unused.
    """
    factory = _get_or_create(company_id)
    return factory()


def close_customer_session(company_id: str):
    """Remove the scoped session for this company (call on teardown / after restore)."""
    if company_id in _session_cache:
        _session_cache[company_id].remove()


def init_customer_db_for_company(company, platform_session=None):
    """
    Called immediately after a new company registers.
    Creates the dedicated SQLite file and all customer tables.
    The `company` object and `platform_session` arguments are accepted for
    backwards compatibility but only company.company_id is used.
    """
    company_id = company.company_id if hasattr(company, "company_id") else company
    factory    = _get_or_create(company_id)
    return factory


def dispose_all():
    """Dispose all cached engines (call on app shutdown)."""
    for engine in _engine_cache.values():
        engine.dispose()
    _engine_cache.clear()
    _session_cache.clear()
