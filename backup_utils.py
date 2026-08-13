"""
backup_utils.py
Backup and restore utilities for the ERP system (local storage only)
"""

import os
import json
import shutil
import zipfile
import hashlib
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
import tempfile

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from platform_models import Company
from db_router import get_customer_session, close_customer_session

# ─────────────────────────────────────────────────────────────────────────────
# Backup Configuration — local storage only, location chosen by the user
# ─────────────────────────────────────────────────────────────────────────────

_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backup_config.json")
_DEFAULT_BACKUP_DIR = os.environ.get("BACKUP_DIR", os.path.join(os.getcwd(), "backups"))


def get_backup_dir() -> str:
    """Return the currently configured local backup folder, creating it if needed."""
    backup_dir = _DEFAULT_BACKUP_DIR
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            saved = cfg.get("backup_dir")
            if saved:
                backup_dir = saved
        except Exception:
            pass
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir


def set_backup_dir(path: str) -> str:
    """Let the user choose where backups are stored on disk."""
    if not path or not path.strip():
        raise Exception("Backup folder path cannot be empty")
    path = path.strip()
    os.makedirs(path, exist_ok=True)
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"backup_dir": path}, f, indent=2)
    return path


BACKUP_DESTINATIONS = {
    "local": "Local Storage",
}


def generate_backup_id():
    """Generate a unique backup ID"""
    return f"BACKUP-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def calculate_file_hash(filepath: str) -> str:
    """Calculate SHA-256 hash of a file"""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def create_company_backup(company_id: str, include_attachments: bool = True, 
                          from_date: date = None, to_date: date = None) -> Dict[str, Any]:
    """
    Create a full backup: all tables to JSON, plus attachment files, zipped.
    
    Args:
        company_id: The company ID to backup
        include_attachments: Whether to include attachment files
        from_date: Optional start date for filtering data (inclusive)
        to_date: Optional end date for filtering data (inclusive)
    """
    backup_dir = get_backup_dir()
    backup_id = generate_backup_id()
    timestamp = datetime.now()

    backup_path = os.path.join(backup_dir, company_id, backup_id)
    os.makedirs(backup_path, exist_ok=True)

    # Store date range in backup info
    backup_info = {
        "backup_id": backup_id,
        "company_id": company_id,
        "timestamp": timestamp.isoformat(),
        "version": "1.0",
        "files": [],
        "size_bytes": 0,
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": to_date.isoformat() if to_date else None,
    }

    try:
        db_backup_file = os.path.join(backup_path, "database.json")
        export_database_to_json(company_id, db_backup_file, from_date, to_date)
        if os.path.exists(db_backup_file):
            backup_info["files"].append({
                "name": "database.json",
                "path": db_backup_file,
                "size": os.path.getsize(db_backup_file)
            })

        if include_attachments:
            attachments_dir = os.path.join(backup_path, "attachments")
            backup_attachments(company_id, attachments_dir, from_date, to_date)
            if os.path.exists(attachments_dir):
                for root, dirs, files in os.walk(attachments_dir):
                    for file in files:
                        filepath = os.path.join(root, file)
                        backup_info["files"].append({
                            "name": file,
                            "path": filepath,
                            "size": os.path.getsize(filepath)
                        })

        metadata_file = os.path.join(backup_path, "backup_metadata.json")
        with open(metadata_file, 'w') as f:
            json.dump(backup_info, f, indent=2, default=str)
        backup_info["files"].append({
            "name": "backup_metadata.json",
            "path": metadata_file,
            "size": os.path.getsize(metadata_file)
        })

        zip_path = os.path.join(backup_dir, f"{backup_id}.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(backup_path):
                for file in files:
                    filepath = os.path.join(root, file)
                    arcname = os.path.relpath(filepath, backup_path)
                    zipf.write(filepath, arcname)

        file_hash = calculate_file_hash(zip_path)
        zip_size = os.path.getsize(zip_path)

        shutil.rmtree(backup_path, ignore_errors=True)

        backup_info["backup_file"] = zip_path
        backup_info["file_hash"] = file_hash
        backup_info["size_bytes"] = zip_size
        backup_info["size_mb"] = round(zip_size / (1024 * 1024), 4)

        save_backup_record(backup_info)

        return backup_info

    except Exception as e:
        if os.path.exists(backup_path):
            shutil.rmtree(backup_path, ignore_errors=True)
        raise Exception(str(e))


def export_database_to_json(company_id: str, output_file: str, 
                            from_date: date = None, to_date: date = None):
    """
    Export all company tables to JSON format with optional date filtering.
    
    Args:
        company_id: The company ID
        output_file: Output file path
        from_date: Optional start date filter (inclusive)
        to_date: Optional end date filter (inclusive)
    """
    from customer_models import (
        CompanyUser, Client, Order, StockItem, Invoice, InvoiceItem,
        Estimate, EstimateItem, PurchaseInvoice, PurchaseInvoiceItem,
        StockPurchaseHistory, CashTransaction, BankAccount, BankTransaction,
        Loan, LoanRepayment, Cheque, PurchasePayment
    )

    cdb = get_customer_session(company_id)

    data = {
        "company_id": company_id,
        "export_date": datetime.now().isoformat(),
        "from_date": from_date.isoformat() if from_date else None,
        "to_date": to_date.isoformat() if to_date else None,
        "tables": {}
    }

    def apply_date_filter(query, model, date_column):
        """Apply date range filters to a query if dates are provided."""
        if from_date:
            query = query.filter(date_column >= from_date)
        if to_date:
            query = query.filter(date_column <= to_date)
        return query

    # Models with company_id directly
    models_with_company_id = [
        ("company_users", CompanyUser),
        ("clients", Client),
        ("orders", Order),
        ("stock_items", StockItem),
        ("invoices", Invoice),
        ("estimates", Estimate),
        ("purchase_invoices", PurchaseInvoice),
        ("cash_transactions", CashTransaction),
        ("bank_accounts", BankAccount),
        ("bank_transactions", BankTransaction),
        ("loans", Loan),
        ("cheques", Cheque),
        ("purchase_payments", PurchasePayment),
    ]

    # Models without company_id directly, linked via a parent
    child_models = [
        ("invoice_items", InvoiceItem, "invoice_id", Invoice),
        ("estimate_items", EstimateItem, "estimate_id", Estimate),
        ("purchase_invoice_items", PurchaseInvoiceItem, "purchase_invoice_id", PurchaseInvoice),
        ("stock_purchase_history", StockPurchaseHistory, "purchase_invoice_id", PurchaseInvoice),
        ("loan_repayments", LoanRepayment, "loan_id", Loan),
    ]

    # Date-filter mapping for each model
    date_column_map = {
        "invoices": Invoice.date,
        "estimates": Estimate.date,
        "purchase_invoices": PurchaseInvoice.date,
        "cash_transactions": CashTransaction.date,
        "bank_transactions": BankTransaction.date,
        "loans": Loan.loan_date,
        "cheques": Cheque.cheque_date,
        "orders": Order.date,
        "stock_purchase_history": StockPurchaseHistory.purchase_date,
        "loan_repayments": LoanRepayment.date,
        "purchase_payments": PurchasePayment.date,
    }

    for table_name, model in models_with_company_id:
        if table_name in ("cheques", "purchase_payments"):
            records = cdb.query(model).all()
        else:
            query = cdb.query(model).filter_by(company_id=company_id)
            # Apply date filter if this model has a date column
            if table_name in date_column_map and (from_date or to_date):
                query = apply_date_filter(query, model, date_column_map[table_name])
            records = query.all()
        
        data["tables"][table_name] = []
        for record in records:
            record_dict = {}
            for column in model.__table__.columns:
                value = getattr(record, column.name)
                if isinstance(value, (datetime, date)):
                    value = value.isoformat()
                record_dict[column.name] = value
            data["tables"][table_name].append(record_dict)

    # Export child records (filtered by parent's date range)
    for table_name, model, fk_name, parent_model in child_models:
        query = cdb.query(model).join(
            parent_model,
            getattr(model, fk_name) == parent_model.id
        ).filter(parent_model.company_id == company_id)
        
        # Apply date filter to parent table if it has a date column
        parent_table_name = parent_model.__tablename__
        if parent_table_name in date_column_map and (from_date or to_date):
            # Apply filter on parent's date column
            date_col = date_column_map[parent_table_name]
            if from_date:
                query = query.filter(date_col >= from_date)
            if to_date:
                query = query.filter(date_col <= to_date)
        
        records = query.all()

        data["tables"][table_name] = []
        for record in records:
            record_dict = {}
            for column in model.__table__.columns:
                value = getattr(record, column.name)
                if isinstance(value, (datetime, date)):
                    value = value.isoformat()
                record_dict[column.name] = value
            data["tables"][table_name].append(record_dict)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, default=str)

    close_customer_session(company_id)


def backup_attachments(company_id: str, output_dir: str, 
                       from_date: date = None, to_date: date = None):
    """
    Backup this company's purchase invoice attachments with optional date filtering.
    
    If date range is provided, only attachments for invoices within that date
    range will be backed up. Since attachments are named with invoice ID,
    we need to check each attachment's corresponding invoice date.
    """
    uploads_dir = "uploads/purchase_invoices"

    if not os.path.exists(uploads_dir):
        return

    # Get all invoice IDs and their dates from the database
    from customer_models import PurchaseInvoice
    cdb = get_customer_session(company_id)
    
    # Query purchase invoices with date filter
    query = cdb.query(PurchaseInvoice.invoice_id, PurchaseInvoice.date).filter(
        PurchaseInvoice.company_id == company_id
    )
    if from_date:
        query = query.filter(PurchaseInvoice.date >= from_date)
    if to_date:
        query = query.filter(PurchaseInvoice.date <= to_date)
    
    invoice_dates = {row[0]: row[1] for row in query.all()}
    
    if not invoice_dates:
        return  # No invoices in date range, skip attachments

    os.makedirs(output_dir, exist_ok=True)
    
    # Match attachments to invoices in the date range
    for filename in os.listdir(uploads_dir):
        if company_id in filename:
            src = os.path.join(uploads_dir, filename)
            if os.path.isfile(src):
                # Extract invoice ID from filename
                # Format: INV-XXXXXX_filename.ext or similar
                parts = filename.split('_')
                if parts:
                    # Check if any part matches an invoice in our date range
                    for part in parts:
                        if part in invoice_dates:
                            shutil.copy2(src, os.path.join(output_dir, filename))
                            break


def save_backup_record(backup_info: Dict[str, Any]):
    """Save backup record to platform database"""
    from platform_models import BackupRecord
    from app import db

    record = BackupRecord(
        backup_id=backup_info["backup_id"],
        company_id=backup_info["company_id"],
        backup_date=datetime.fromisoformat(backup_info["timestamp"]),
        backup_file_path=backup_info["backup_file"],
        file_size_mb=backup_info["size_mb"],
        file_hash=backup_info["file_hash"],
        status="completed",
        # Add date range fields
        backup_from_date=date.fromisoformat(backup_info["from_date"]) if backup_info.get("from_date") else None,
        backup_to_date=date.fromisoformat(backup_info["to_date"]) if backup_info.get("to_date") else None,
    )
    db.session.add(record)
    db.session.commit()


def list_backups(company_id: str = None) -> List[Dict[str, Any]]:
    """List all available backups"""
    from platform_models import BackupRecord

    query = BackupRecord.query
    if company_id:
        query = query.filter_by(company_id=company_id)

    backups = query.order_by(BackupRecord.backup_date.desc()).all()

    return [{
        "backup_id": b.backup_id,
        "company_id": b.company_id,
        "backup_date": b.backup_date,
        "file_size_mb": b.file_size_mb,
        "status": b.status,
        "restore_date": b.restore_date,
        "restored_by": b.restored_by,
        "backup_from_date": b.backup_from_date,
        "backup_to_date": b.backup_to_date,
    } for b in backups]


def restore_from_backup(backup_id, user_email):
    """Restore company data from a backup zip file."""
    from platform_models import BackupRecord
    from app import db

    backup_record = BackupRecord.query.filter_by(backup_id=backup_id).first()
    if not backup_record:
        raise Exception(f"Backup {backup_id} not found")

    if not os.path.exists(backup_record.backup_file_path):
        raise Exception(f"Backup file not found on disk: {backup_record.backup_file_path}")

    with tempfile.TemporaryDirectory() as temp_dir:
        with zipfile.ZipFile(backup_record.backup_file_path, 'r') as zipf:
            zipf.extractall(temp_dir)

        db_json_file = os.path.join(temp_dir, "database.json")
        if os.path.exists(db_json_file):
            restore_database_from_json(backup_record.company_id, db_json_file)
        else:
            sql_files = [f for f in os.listdir(temp_dir) if f.endswith('.sql')]
            if not sql_files:
                raise Exception(
                    f"No database.json or .sql file found in backup {backup_id}. "
                    f"Zip contained: {os.listdir(temp_dir) or '(empty)'}"
                )
            _restore_legacy_sql_dump(backup_record.company_id, os.path.join(temp_dir, sql_files[0]))

        attachments_dir = os.path.join(temp_dir, "attachments")
        if os.path.exists(attachments_dir):
            restore_attachments(backup_record.company_id, attachments_dir)

    backup_record.restore_date = datetime.now()
    backup_record.restored_by = user_email
    db.session.commit()

    return {
        "backup_id": backup_id,
        "company_id": backup_record.company_id,
        "restore_date": datetime.now(),
        "restored_by": user_email,
        "status": "completed"
    }


def restore_from_uploaded_backup(company_id, file_path, user_email):
    """Restore from an uploaded backup zip file."""
    try:
        if not zipfile.is_zipfile(file_path):
            return {"success": False, "message": "Invalid zip file - not a valid archive"}

        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)

            db_json_file = os.path.join(temp_dir, "database.json")
            if os.path.exists(db_json_file):
                restore_database_from_json(company_id, db_json_file)
            else:
                sql_files = [f for f in os.listdir(temp_dir) if f.endswith('.sql')]
                if not sql_files:
                    return {
                        "success": False,
                        "message": (
                            f"No database.json or .sql file found in the uploaded "
                            f"archive. It contained: {os.listdir(temp_dir) or '(empty)'}"
                        )
                    }
                _restore_legacy_sql_dump(company_id, os.path.join(temp_dir, sql_files[0]))

            attachments_dir = os.path.join(temp_dir, 'attachments')
            if os.path.exists(attachments_dir):
                restore_attachments(company_id, attachments_dir)

            try:
                from platform_models import BackupRecord
                from app import db
                backup_record = BackupRecord.query.filter_by(
                    company_id=company_id
                ).order_by(BackupRecord.backup_date.desc()).first()
                if backup_record:
                    backup_record.restore_date = datetime.utcnow()
                    backup_record.restored_by = user_email
                    db.session.commit()
            except Exception as e:
                print(f"⚠️ Could not log restore in platform DB: {e}")

            return {"success": True, "message": "Restore completed successfully"}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "message": str(e)}


def _restore_legacy_sql_dump(company_id: str, sql_file: str):
    """Only reached for backups made by the short-lived raw-SQL dump format."""
    from db_router import _engine_cache, _get_or_create
    engine = _engine_cache.get(company_id)
    if engine is None:
        _get_or_create(company_id)
        engine = _engine_cache[company_id]

    with open(sql_file, 'r', encoding='utf-8') as f:
        sql_content = f.read()

    with engine.connect() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        try:
            for stmt in sql_content.split(';'):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(text(stmt))
            conn.commit()
        finally:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            conn.commit()


def restore_attachments(company_id, attachments_dir):
    """Restore attachments from backup into the folder app.py actually serves from."""
    uploads_dir = "uploads/purchase_invoices"
    os.makedirs(uploads_dir, exist_ok=True)

    for filename in os.listdir(attachments_dir):
        src = os.path.join(attachments_dir, filename)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(uploads_dir, filename))


def _coerce_record_dates(record_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert date/datetime strings back to Python objects."""
    for key, value in record_data.items():
        if isinstance(value, str):
            if "date" in key.lower() or key.endswith("_date"):
                try:
                    record_data[key] = datetime.fromisoformat(value).date()
                    continue
                except Exception:
                    pass
            if "created_at" in key.lower() or "updated_at" in key.lower():
                try:
                    record_data[key] = datetime.fromisoformat(value)
                except Exception:
                    pass
    return record_data


def restore_database_from_json(company_id: str, json_file: str):
    """
    Restore database from JSON export.
    """
    from customer_models import (
        CompanyUser, Client, Order, StockItem, Invoice, InvoiceItem,
        Estimate, EstimateItem, PurchaseInvoice, PurchaseInvoiceItem,
        StockPurchaseHistory, CashTransaction, BankAccount, BankTransaction,
        Loan, LoanRepayment, Cheque, PurchasePayment
    )

    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if data["company_id"] != company_id:
        raise Exception(f"Backup is for company {data['company_id']}, cannot restore to {company_id}")

    cdb = get_customer_session(company_id)

    tables = [
        ("company_users", CompanyUser),
        ("clients", Client),
        ("orders", Order),
        ("stock_items", StockItem),
        ("invoices", Invoice),
        ("invoice_items", InvoiceItem),
        ("estimates", Estimate),
        ("estimate_items", EstimateItem),
        ("purchase_invoices", PurchaseInvoice),
        ("purchase_invoice_items", PurchaseInvoiceItem),
        ("stock_purchase_history", StockPurchaseHistory),
        ("cash_transactions", CashTransaction),
        ("bank_accounts", BankAccount),
        ("bank_transactions", BankTransaction),
        ("loans", Loan),
        ("loan_repayments", LoanRepayment),
        ("cheques", Cheque),
        ("purchase_payments", PurchasePayment),
    ]

    cdb.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    try:
        for table_name, model in tables:
            cdb.query(model).delete(synchronize_session=False)
        for table_name, model in tables:
            for record_data in data["tables"].get(table_name, []):
                record_data = _coerce_record_dates(dict(record_data))
                cdb.add(model(**record_data))
        cdb.commit()
    finally:
        cdb.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        cdb.commit()

    close_customer_session(company_id)


def delete_backup(backup_id: str) -> bool:
    """Delete a backup file and its record"""
    from platform_models import BackupRecord
    from app import db

    backup_record = BackupRecord.query.filter_by(backup_id=backup_id).first()
    if not backup_record:
        return False

    if os.path.exists(backup_record.backup_file_path):
        os.remove(backup_record.backup_file_path)

    db.session.delete(backup_record)
    db.session.commit()

    return True