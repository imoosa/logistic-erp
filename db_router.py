"""
db_router.py  ── RENDER / SQLite edition
─────────────────────────────────────────
Platform DB  → single SQLite file   (PLATFORM_DB_URI env var  OR  /data/platform.db)
Customer DB  → one SQLite file per company, stored under DATA_DIR

File-naming pattern:   <DATA_DIR>/erp_<company_id_lowercase>.db

Environment variables
─────────────────────
DATA_DIR        Directory for all SQLite files   (default: /data)
                On Render, mount a Persistent Disk at /data so files survive deploys.
                Locally you can set DATA_DIR=./local_data for testing.

PLATFORM_DB_URI Full SQLAlchemy URI for the platform DB.
                If not set, defaults to sqlite:///<DATA_DIR>/platform.db
                (You can override with a Postgres/MySQL URI on Render if you prefer.)

Usage in routes
───────────────
    from db_router import get_customer_session, close_customer_session
    session = get_customer_session(company_id)
    users   = session.query(CompanyUser).all()
    close_customer_session(company_id)
"""

import os
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, scoped_session
from customer_models import customer_db   # exposes .metadata (plain SQLAlchemy Base)

# ─────────────────────────────────────────────────────────────────────────────
# Data directory — Render persistent disk should be mounted here
# ─────────────────────────────────────────────────────────────────────────────
_DATA_DIR_ENV = os.environ.get("DATA_DIR", "/data")

def _get_data_dir() -> str:
    """
    Return a writable data directory, creating it if needed.
    Falls back to /tmp/erp_data if the configured path isn't available yet
    (e.g. during Render's build phase before the persistent disk is mounted).
    /tmp is ephemeral — data there is lost on redeploy, so always mount the
    Render Persistent Disk at /data and set DATA_DIR=/data in env vars.
    """
    for candidate in (_DATA_DIR_ENV, "/tmp/erp_data"):
        try:
            os.makedirs(candidate, exist_ok=True)
            test_file = os.path.join(candidate, ".write_test")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
            return candidate
        except OSError:
            continue
    raise RuntimeError("No writable data directory found. Set DATA_DIR env var.")

# ─────────────────────────────────────────────────────────────────────────────
# In-process cache:  { company_id → scoped_session factory }
# ─────────────────────────────────────────────────────────────────────────────
_engine_cache:  dict = {}
_session_cache: dict = {}


def _db_path(company_id: str) -> str:
    """Absolute path to the SQLite file for a company. Resolves data dir at runtime."""
    return os.path.join(_get_data_dir(), f"erp_{company_id.lower()}.db")


def _build_uri(company_id: str) -> str:
    """Build the sqlite:/// URI for a company's dedicated database."""
    return f"sqlite:///{_db_path(company_id)}"


def _enable_wal_and_fk(engine):
    """
    Enable WAL mode (better concurrent read performance) and
    foreign-key enforcement for every new SQLite connection.
    """
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _get_or_create(company_id: str):
    """
    Build (or return cached) scoped_session factory for a company.
    Creates the SQLite file and all customer tables on first call.
    """
    if company_id not in _engine_cache:
        uri    = _build_uri(company_id)
        engine = create_engine(
            uri,
            connect_args={"check_same_thread": False},   # required for Flask
            pool_pre_ping=True,
        )
        _enable_wal_and_fk(engine)

        # Create all customer tables if they don't exist yet
        customer_db.metadata.create_all(engine)

        factory = scoped_session(sessionmaker(bind=engine))
        _engine_cache[company_id]  = engine
        _session_cache[company_id] = factory

    return _session_cache[company_id]


# ─────────────────────────────────────────────────────────────────────────────
# Public API (same interface as the MySQL version)
# ─────────────────────────────────────────────────────────────────────────────

def get_customer_session(company_id: str, db_session=None):
    """
    Return a SQLAlchemy session bound to this company's SQLite database.

    db_session is accepted for API compatibility but is ignored —
    the path is always derived from company_id + DATA_DIR.
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


# ─────────────────────────────────────────────────────────────────────────────
# Migration helpers (kept for compatibility with any migrate_customer_db usage)
# ─────────────────────────────────────────────────────────────────────────────

def get_platform_engine():
    """Get the platform database engine. Safe to call only at runtime, not import time."""
    platform_uri = os.environ.get(
        "PLATFORM_DB_URI",
        f"sqlite:///{os.path.join(_get_data_dir(), 'platform.db')}"
    )
    engine = create_engine(platform_uri, connect_args={"check_same_thread": False})
    _enable_wal_and_fk(engine)
    return engine


def get_target_companies(target_type="all", target_db="", where_clause=""):
    """
    Get list of active Company objects.
    Returns list of company objects from the platform DB.
    """
    from platform_models import Company

    query = Company.query.filter_by(is_active=True)

    if where_clause:
        try:
            query = query.filter(text(where_clause))
        except Exception as e:
            print(f"Warning: Could not apply custom WHERE clause: {e}")

    companies = query.all()

    if target_db == "platform":
        return []   # platform DB is handled separately
    return companies


def filter_companies_by_table(companies, table_name):
    """
    Filter companies to those whose SQLite DB already contains table_name.
    Useful for targeted migrations.
    """
    from sqlalchemy import inspect

    filtered = []
    for company in companies:
        try:
            engine = _engine_cache.get(company.company_id)
            if engine is None:
                _get_or_create(company.company_id)
                engine = _engine_cache[company.company_id]

            inspector = inspect(engine)
            if table_name in inspector.get_table_names():
                filtered.append(company)
        except Exception:
            filtered.append(company)   # include on error to be safe

    return filtered
