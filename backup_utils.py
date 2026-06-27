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

# Where we remember the user-chosen backup folder. This file lives next to
# this module, NOT inside the backup folder itself (so it survives even if
# the user points the backup folder somewhere else).
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
    os.makedirs(path, exist_ok=True)  # raises a clear error if the path is invalid/unwritable
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"backup_dir": path}, f, indent=2)
    return path


# Kept only so existing imports of BACKUP_DESTINATIONS elsewhere don't crash.
# Local storage is the only supported destination now.
BACKUP_DESTINATIONS = {
    "local": "Local Storage",
}

# ─────────────────────────────────────────────────────────────────────────────
# Core Backup Functions
# ─────────────────────────────────────────────────────────────────────────────

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


def create_company_backup(company_id: str, include_attachments: bool = True) -> Dict[str, Any]:
    """
    Create a complete backup of a company's data on local disk.
    Returns: Dict with backup info
    """
    backup_dir = get_backup_dir()
    backup_id = generate_backup_id()
    timestamp = datetime.now()

    # Create backup working directory
    backup_path = os.path.join(backup_dir, company_id, backup_id)
    os.makedirs(backup_path, exist_ok=True)

    backup_info = {
        "backup_id": backup_id,
        "company_id": company_id,
        "timestamp": timestamp.isoformat(),
        "version": "1.0",
        "files": [],
        "size_bytes": 0,
    }

    try:
        # 1. Export database data to JSON
        db_backup_file = os.path.join(backup_path, "database.json")
        export_database_to_json(company_id, db_backup_file)
        if os.path.exists(db_backup_file):
            backup_info["files"].append({
                "name": "database.json",
                "path": db_backup_file,
                "size": os.path.getsize(db_backup_file)
            })

        # 2. Backup attachments (purchase invoices, etc.)
        if include_attachments:
            attachments_dir = os.path.join(backup_path, "attachments")
            backup_attachments(company_id, attachments_dir)
            if os.path.exists(attachments_dir):
                for root, dirs, files in os.walk(attachments_dir):
                    for file in files:
                        filepath = os.path.join(root, file)
                        backup_info["files"].append({
                            "name": file,
                            "path": filepath,
                            "size": os.path.getsize(filepath)
                        })

        # 3. Create metadata file
        metadata_file = os.path.join(backup_path, "backup_metadata.json")
        with open(metadata_file, 'w') as f:
            json.dump(backup_info, f, indent=2)
        backup_info["files"].append({
            "name": "backup_metadata.json",
            "path": metadata_file,
            "size": os.path.getsize(metadata_file)
        })

        # 4. Create zip archive
        zip_path = os.path.join(backup_dir, f"{backup_id}.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(backup_path):
                for file in files:
                    filepath = os.path.join(root, file)
                    arcname = os.path.relpath(filepath, backup_path)
                    zipf.write(filepath, arcname)

        # Calculate hash and size
        file_hash = calculate_file_hash(zip_path)
        zip_size = os.path.getsize(zip_path)

        # Clean up temporary working directory
        shutil.rmtree(backup_path, ignore_errors=True)

        backup_info["backup_file"] = zip_path
        backup_info["file_hash"] = file_hash
        backup_info["size_bytes"] = zip_size
        backup_info["size_mb"] = round(zip_size / (1024 * 1024), 4)

        # Save backup record
        save_backup_record(backup_info)

        return backup_info

    except Exception as e:
        # Clean up on error
        if os.path.exists(backup_path):
            shutil.rmtree(backup_path, ignore_errors=True)
        raise Exception(str(e))


def export_database_to_json(company_id: str, output_file: str):
    """Export all company tables to JSON format"""
    from customer_models import (
        CompanyUser, Client, Order, StockItem, Invoice, InvoiceItem,
        Estimate, EstimateItem, PurchaseInvoice, PurchaseInvoiceItem,
        StockPurchaseHistory, CashTransaction, BankAccount, BankTransaction,
        Loan, LoanRepayment
    )

    cdb = get_customer_session(company_id)

    data = {
        "company_id": company_id,
        "export_date": datetime.now().isoformat(),
        "tables": {}
    }

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
    ]

    # Models without company_id directly, linked via a parent
    child_models = [
        ("invoice_items", InvoiceItem, "invoice_id", Invoice),
        ("estimate_items", EstimateItem, "estimate_id", Estimate),
        ("purchase_invoice_items", PurchaseInvoiceItem, "purchase_invoice_id", PurchaseInvoice),
        ("stock_purchase_history", StockPurchaseHistory, "purchase_invoice_id", PurchaseInvoice),
        ("loan_repayments", LoanRepayment, "loan_id", Loan),
    ]

    for table_name, model in models_with_company_id:
        records = cdb.query(model).filter_by(company_id=company_id).all()
        data["tables"][table_name] = []
        for record in records:
            record_dict = {}
            for column in model.__table__.columns:
                value = getattr(record, column.name)
                if isinstance(value, (datetime, date)):
                    value = value.isoformat()
                record_dict[column.name] = value
            data["tables"][table_name].append(record_dict)

    for table_name, model, fk_name, parent_model in child_models:
        records = cdb.query(model).join(
            parent_model,
            getattr(model, fk_name) == parent_model.id
        ).filter(parent_model.company_id == company_id).all()

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


def backup_attachments(company_id: str, output_dir: str):
    """Backup this company's purchase invoice attachments"""
    uploads_dir = "uploads/purchase_invoices"

    if os.path.exists(uploads_dir):
        os.makedirs(output_dir, exist_ok=True)  # FIX: this dir was never created before
        for filename in os.listdir(uploads_dir):
            if company_id in filename:  # FIX: removed "or True" which copied every tenant's files
                src = os.path.join(uploads_dir, filename)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(output_dir, filename))


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
        status="completed"
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
    } for b in backups]


def restore_from_backup(backup_id: str, restored_by: str = None) -> Dict[str, Any]:
    """
    Restore a company's data from a local backup file.
    Returns: Dict with restore info
    """
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

        attachments_dir = os.path.join(temp_dir, "attachments")
        if os.path.exists(attachments_dir):
            restore_attachments(backup_record.company_id, attachments_dir)

    backup_record.restore_date = datetime.now()
    backup_record.restored_by = restored_by
    db.session.commit()

    return {
        "backup_id": backup_id,
        "company_id": backup_record.company_id,
        "restore_date": datetime.now(),
        "restored_by": restored_by,
        "status": "completed"
    }


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

    IDs are auto-generated again on insert (old primary keys are not reused),
    so every foreign key column that pointed at an old ID has to be rewritten
    to point at the new ID once the parent row has been re-inserted. This is
    done with an old_id -> new_id map built up table by table, in the same
    parent-before-child order the rows are inserted in.
    """
    from customer_models import (
        CompanyUser, Client, Order, StockItem, Invoice, InvoiceItem,
        Estimate, EstimateItem, PurchaseInvoice, PurchaseInvoiceItem,
        StockPurchaseHistory, CashTransaction, BankAccount, BankTransaction,
        Loan, LoanRepayment
    )

    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if data["company_id"] != company_id:
        raise Exception(f"Backup is for company {data['company_id']}, cannot restore to {company_id}")

    cdb = get_customer_session(company_id)

    # ── 1. Clear existing data (children first, then parents) ──────────────
    clear_order = [
        ("loan_repayments", LoanRepayment, "loan_id", Loan),
        ("bank_transactions", BankTransaction, "bank_account_id", BankAccount),
        ("stock_purchase_history", StockPurchaseHistory, "purchase_invoice_id", PurchaseInvoice),
        ("purchase_invoice_items", PurchaseInvoiceItem, "purchase_invoice_id", PurchaseInvoice),
        ("invoice_items", InvoiceItem, "invoice_id", Invoice),
        ("estimate_items", EstimateItem, "estimate_id", Estimate),
    ]
    for table_name, model, fk_name, parent_model in clear_order:
        cdb.query(model).filter(
            getattr(model, fk_name).in_(
                cdb.query(parent_model.id).filter(parent_model.company_id == company_id)
            )
        ).delete(synchronize_session=False)

    parent_tables = [
        ("loans", Loan),
        ("bank_accounts", BankAccount),
        ("cash_transactions", CashTransaction),
        ("purchase_invoices", PurchaseInvoice),
        ("invoices", Invoice),
        ("estimates", Estimate),
        ("orders", Order),
        ("stock_items", StockItem),
        ("clients", Client),
        ("company_users", CompanyUser),
    ]
    for table_name, model in parent_tables:
        cdb.query(model).filter_by(company_id=company_id).delete()

    cdb.flush()

    # ── 2. Re-insert top-level tables and remember old_id -> new_id ────────
    # (these have no FK to anything else we're restoring)
    top_level = [
        ("company_users", CompanyUser),
        ("clients", Client),
        ("stock_items", StockItem),
        ("bank_accounts", BankAccount),
        ("loans", Loan),
    ]

    id_maps: Dict[str, Dict[Any, Any]] = {}

    for table_name, model in top_level:
        id_map = {}
        for record_data in data["tables"].get(table_name, []):
            record_data = dict(record_data)
            old_id = record_data.pop("id", None)
            record_data = _coerce_record_dates(record_data)
            record = model(**record_data)
            cdb.add(record)
            cdb.flush()  # need record.id populated immediately
            if old_id is not None:
                id_map[old_id] = record.id
        id_maps[table_name] = id_map

    # ── 3. Tables that reference a top-level table by FK ────────────────────
    # (invoices/estimates/purchase_invoices reference clients; orders too)
    second_level = [
        ("invoices", Invoice, [("client_id", "clients")]),
        ("estimates", Estimate, [("client_id", "clients")]),
        ("purchase_invoices", PurchaseInvoice, [("client_id", "clients")]),
        ("orders", Order, [("client_id", "clients")]),
    ]

    for table_name, model, fk_specs in second_level:
        id_map = {}
        for record_data in data["tables"].get(table_name, []):
            record_data = dict(record_data)
            old_id = record_data.pop("id", None)
            record_data = _coerce_record_dates(record_data)
            for fk_col, parent_table in fk_specs:
                if fk_col in record_data and record_data[fk_col] is not None:
                    record_data[fk_col] = id_maps.get(parent_table, {}).get(
                        record_data[fk_col], record_data[fk_col]
                    )
            record = model(**record_data)
            cdb.add(record)
            cdb.flush()
            if old_id is not None:
                id_map[old_id] = record.id
        id_maps[table_name] = id_map

    # ── 4. Leaf / line-item tables that reference a second-level table ──────
    leaf_tables = [
        ("invoice_items", InvoiceItem, [("invoice_id", "invoices")]),
        ("estimate_items", EstimateItem, [("estimate_id", "estimates")]),
        ("purchase_invoice_items", PurchaseInvoiceItem, [("purchase_invoice_id", "purchase_invoices")]),
        ("stock_purchase_history", StockPurchaseHistory, [("purchase_invoice_id", "purchase_invoices")]),
        ("cash_transactions", CashTransaction, []),
        ("bank_transactions", BankTransaction, [("bank_account_id", "bank_accounts")]),
        ("loan_repayments", LoanRepayment, [("loan_id", "loans")]),
    ]

    for table_name, model, fk_specs in leaf_tables:
        for record_data in data["tables"].get(table_name, []):
            record_data = dict(record_data)
            record_data.pop("id", None)
            record_data = _coerce_record_dates(record_data)
            for fk_col, parent_table in fk_specs:
                if fk_col in record_data and record_data[fk_col] is not None:
                    record_data[fk_col] = id_maps.get(parent_table, {}).get(
                        record_data[fk_col], record_data[fk_col]
                    )
            record = model(**record_data)
            cdb.add(record)

    cdb.commit()
    close_customer_session(company_id)


def restore_attachments(company_id: str, attachments_dir: str):
    """Restore attachments from backup"""
    uploads_dir = "uploads/purchase_invoices"
    os.makedirs(uploads_dir, exist_ok=True)

    for filename in os.listdir(attachments_dir):
        src = os.path.join(attachments_dir, filename)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(uploads_dir, filename))


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
