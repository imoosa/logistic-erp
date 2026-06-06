"""
db_router.py
────────────
Manages per-company database connections.

Platform DB  → YOUR MySQL (configured via PLATFORM_DB_URI env var in app.py)
Customer DB  → Separate MySQL database on the SAME VPS, one per company.
               Name pattern:  erp_<company_id_lowercase>
               URI built from env vars: VPS_MYSQL_HOST/PORT/USER/PASSWORD

Every company that registers gets its own isolated MySQL database created
automatically. No SQLite, no cloud storage — everything stays on the VPS.

Environment variables
─────────────────────
VPS_MYSQL_HOST      MySQL host              (default: 127.0.0.1)
VPS_MYSQL_PORT      MySQL port              (default: 3306)
VPS_MYSQL_USER      MySQL user              (default: root)
VPS_MYSQL_PASSWORD  MySQL password          (default: "")

Usage in routes
───────────────
    from db_router import get_customer_session, close_customer_session
    session = get_customer_session(company_id)
    users   = session.query(CompanyUser).all()
    close_customer_session(company_id)
"""

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session
from customer_models import customer_db   # exposes .metadata (plain SQLAlchemy Base)

# ─────────────────────────────────────────────────────────────────────────────
# MySQL connection settings for customer databases on this VPS
# ─────────────────────────────────────────────────────────────────────────────
VPS_MYSQL_HOST     = os.environ.get("VPS_MYSQL_HOST",     "127.0.0.1")
VPS_MYSQL_PORT     = os.environ.get("VPS_MYSQL_PORT",     "3306")
VPS_MYSQL_USER     = os.environ.get("VPS_MYSQL_USER",     "root")
VPS_MYSQL_PASSWORD = os.environ.get("VPS_MYSQL_PASSWORD", "")

# ─────────────────────────────────────────────────────────────────────────────
# In-process cache:  { company_id → scoped_session factory }
# ─────────────────────────────────────────────────────────────────────────────
_engine_cache:  dict = {}
_session_cache: dict = {}


def _db_name(company_id: str) -> str:
    """Return the MySQL database name for a company."""
    return f"erp_{company_id.lower()}"


def _build_uri(company_id: str) -> str:
    """Build the mysql+pymysql URI for a company's dedicated database."""
    db_name = _db_name(company_id)
    pwd     = VPS_MYSQL_PASSWORD
    return (
        f"mysql+pymysql://{VPS_MYSQL_USER}:{pwd}"
        f"@{VPS_MYSQL_HOST}:{VPS_MYSQL_PORT}/{db_name}"
    )


def _create_database_if_missing(company_id: str):
    """
    Issue CREATE DATABASE IF NOT EXISTS on the VPS MySQL server.
    Uses a root-level connection (no database selected).
    """
    db_name = _db_name(company_id)
    root_uri = (
        f"mysql+pymysql://{VPS_MYSQL_USER}:{VPS_MYSQL_PASSWORD}"
        f"@{VPS_MYSQL_HOST}:{VPS_MYSQL_PORT}/"
    )
    engine = create_engine(root_uri)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            ))
            conn.commit()
    finally:
        engine.dispose()


def _get_or_create(company_id: str):
    """
    Build (or return cached) scoped_session factory for a company.
    Creates the MySQL database and all customer tables on first call.
    """
    if company_id not in _engine_cache:
        # 1. Make sure the database exists on this VPS
        _create_database_if_missing(company_id)

        # 2. Build engine pointed at that database
        uri    = _build_uri(company_id)
        engine = create_engine(uri, pool_pre_ping=True, pool_recycle=3600)

        # 3. Create all customer tables if they don't exist yet
        customer_db.metadata.create_all(engine)

        factory = scoped_session(sessionmaker(bind=engine))
        _engine_cache[company_id]  = engine
        _session_cache[company_id] = factory

    return _session_cache[company_id]


def get_customer_session(company_id: str, db_session=None):
    """
    Return a SQLAlchemy session bound to this company's MySQL database.

    db_session is accepted for API compatibility but is no longer needed
    (the URI is always derived from the company_id + env vars).
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
    Creates the dedicated MySQL database and all customer tables.
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
