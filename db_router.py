"""
db_router.py (SQLite version for Render)
────────────
Manages per-company database connections using SQLite files.
Each company gets its own SQLite database file.
"""

import os
from sqlalchemy import create_engine, text
from sqlalchemy.exc import PendingRollbackError, OperationalError
from sqlalchemy.orm import sessionmaker, scoped_session
from customer_models import customer_db

# ─────────────────────────────────────────────────────────────────────────────
# In-process cache:  { company_id → scoped_session factory }
# ─────────────────────────────────────────────────────────────────────────────
_engine_cache:  dict = {}
_session_cache: dict = {}


def _db_path(company_id: str) -> str:
    """Return the SQLite database file path for a company."""
    # Create a directory for customer databases if it doesn't exist
    os.makedirs('customer_dbs', exist_ok=True)
    return f"customer_dbs/erp_{company_id.lower()}.db"


def _build_uri(company_id: str) -> str:
    """Build the SQLite URI for a company's database."""
    db_path = _db_path(company_id)
    return f"sqlite:///{db_path}"


def _get_or_create(company_id: str):
    """
    Build (or return cached) scoped_session factory for a company.
    Creates the SQLite database and all customer tables on first call.
    """
    if company_id not in _engine_cache:
        # Build engine pointed at the SQLite database
        uri = _build_uri(company_id)
        engine = create_engine(
            uri,
            connect_args={'check_same_thread': False},
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=10,
            max_overflow=20,
        )

        # Create all customer tables if they don't exist yet
        customer_db.metadata.create_all(engine)

        factory = scoped_session(sessionmaker(bind=engine))
        _engine_cache[company_id] = engine
        _session_cache[company_id] = factory

    return _session_cache[company_id]


def get_customer_session(company_id: str, db_session=None):
    """
    Return a SQLAlchemy session bound to this company's SQLite database.
    """
    factory = _get_or_create(company_id)
    return factory()


def close_customer_session(company_id: str):
    """Remove the scoped session for this company."""
    if company_id in _session_cache:
        _session_cache[company_id].remove()


def get_customer_session_with_retry(company_id: str, max_retries: int = 1):
    """
    Same as get_customer_session(), but self-heals a session that was left broken.
    """
    last_error = None
    for attempt in range(max_retries + 1):
        session = get_customer_session(company_id)
        try:
            session.execute(text("SELECT 1"))
            return session
        except PendingRollbackError as e:
            last_error = e
            try:
                session.rollback()
            except Exception:
                pass
        except OperationalError as e:
            last_error = e
            if "2006" in str(e) or "2013" in str(e) or "gone away" in str(e):
                if company_id in _session_cache:
                    _session_cache[company_id].remove()
                    del _session_cache[company_id]
                if company_id in _engine_cache:
                    _engine_cache[company_id].dispose()
                    del _engine_cache[company_id]
            else:
                raise
    raise last_error


def init_customer_db_for_company(company, platform_session=None):
    """
    Called immediately after a new company registers.
    Creates the SQLite database and all customer tables.
    """
    company_id = company.company_id if hasattr(company, "company_id") else company
    factory = _get_or_create(company_id)
    return factory


def dispose_all():
    """Dispose all cached engines (call on app shutdown)."""
    for engine in _engine_cache.values():
        engine.dispose()
    _engine_cache.clear()
    _session_cache.clear()


def get_platform_engine():
    """Get the platform database engine."""
    from sqlalchemy import create_engine
    import os
    
    platform_db_uri = os.environ.get(
        "PLATFORM_DB_URI",
        "sqlite:///platform.db"
    )
    return create_engine(platform_db_uri)


def get_target_companies(target_type="all", target_db="", where_clause=""):
    """Get list of target companies based on filters."""
    from platform_models import Company, db
    
    query = Company.query.filter_by(is_active=True)
    
    if where_clause:
        try:
            query = query.filter(text(where_clause))
        except Exception as e:
            print(f"Warning: Could not apply custom WHERE clause: {e}")
    
    companies = query.all()
    
    if target_db == "customer":
        return companies
    elif target_db == "platform":
        return []
    else:
        return companies


def filter_companies_by_table(companies, table_name):
    """Filter companies based on whether they have the specified table."""
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
            filtered.append(company)
    
    return filtered
