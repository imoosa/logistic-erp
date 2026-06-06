"""
backup_utils.py
Backup and restore utilities for the ERP system
"""

import os
import json
import shutil
import zipfile
import hashlib
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
import tempfile

# For cloud storage support - wrap in try-except
try:
    import boto3
except ImportError:
    boto3 = None

try:
    from google.cloud import storage
except ImportError:
    storage = None

try:
    import paramiko
except ImportError:
    paramiko = None

# Database imports
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Platform models
from platform_models import Company
from db_router import get_customer_session, close_customer_session

# ─────────────────────────────────────────────────────────────────────────────
# Backup Configuration
# ─────────────────────────────────────────────────────────────────────────────

BACKUP_DIR = os.environ.get("BACKUP_DIR", "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

# Supported backup destinations
BACKUP_DESTINATIONS = {
    "local": "Local Storage",
    "s3": "Amazon S3",
    "gcs": "Google Cloud Storage",
    "ftp": "FTP/SFTP Server",
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
    Create a complete backup of a company's data
    Returns: Dict with backup info
    """
    backup_id = generate_backup_id()
    timestamp = datetime.now()
    
    # Create backup directory
    backup_path = os.path.join(BACKUP_DIR, company_id, backup_id)
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
        zip_path = os.path.join(BACKUP_DIR, f"{backup_id}.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(backup_path):
                for file in files:
                    filepath = os.path.join(root, file)
                    arcname = os.path.relpath(filepath, backup_path)
                    zipf.write(filepath, arcname)
        
        # Calculate hash and size
        file_hash = calculate_file_hash(zip_path)
        zip_size = os.path.getsize(zip_path)
        
        # Clean up temporary directory
        shutil.rmtree(backup_path)
        
        backup_info["backup_file"] = zip_path
        backup_info["file_hash"] = file_hash
        backup_info["size_bytes"] = zip_size
        backup_info["size_mb"] = round(zip_size / (1024 * 1024), 2)
        
        # Save backup record
        save_backup_record(backup_info)
        
        return backup_info
        
    except Exception as e:
        # Clean up on error
        if os.path.exists(backup_path):
            shutil.rmtree(backup_path)
        raise Exception(f"Backup failed: {str(e)}")

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
    
    # Define which models have company_id directly vs need filtering through parent
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
    
    # These models don't have company_id directly, they're linked via parent
    child_models = [
        ("invoice_items", InvoiceItem, "invoice_id", Invoice),
        ("estimate_items", EstimateItem, "estimate_id", Estimate),
        ("purchase_invoice_items", PurchaseInvoiceItem, "purchase_invoice_id", PurchaseInvoice),
        ("stock_purchase_history", StockPurchaseHistory, "purchase_invoice_id", PurchaseInvoice),
        ("loan_repayments", LoanRepayment, "loan_id", Loan),
    ]
    
    # Export models with direct company_id
    for table_name, model in models_with_company_id:
        records = cdb.query(model).filter_by(company_id=company_id).all()
        data["tables"][table_name] = []
        
        for record in records:
            # Convert SQLAlchemy object to dict
            record_dict = {}
            for column in model.__table__.columns:
                value = getattr(record, column.name)
                # Handle datetime/date objects
                if isinstance(value, (datetime, date)):
                    value = value.isoformat()
                record_dict[column.name] = value
            data["tables"][table_name].append(record_dict)
    
    # Export child models (filter through parent relationship)
    for table_name, model, fk_name, parent_model in child_models:
        # Get all records for this company by joining with parent
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
    
    # Write to file
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, default=str)
    
    close_customer_session(company_id)

def backup_attachments(company_id: str, output_dir: str):
    """Backup all attachments (purchase invoices, etc.)"""
    uploads_dir = f"uploads/purchase_invoices"
    
    if os.path.exists(uploads_dir):
        # Copy all files from the company's uploads
        for filename in os.listdir(uploads_dir):
            if company_id in filename or True:  # Adjust filtering as needed
                src = os.path.join(uploads_dir, filename)
                dst = os.path.join(output_dir, filename)
                shutil.copy2(src, dst)

def save_backup_record(backup_info: Dict[str, Any]):
    """Save backup record to platform database"""
    from platform_models import BackupRecord
    
    # Import here to avoid circular imports
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
    from app import db
    
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
    Restore a company's data from a backup
    Returns: Dict with restore info
    """
    from platform_models import BackupRecord
    from app import db
    
    # Get backup record
    backup_record = BackupRecord.query.filter_by(backup_id=backup_id).first()
    if not backup_record:
        raise Exception(f"Backup {backup_id} not found")
    
    if not os.path.exists(backup_record.backup_file_path):
        raise Exception(f"Backup file not found: {backup_record.backup_file_path}")
    
    # Create temporary directory for extraction
    with tempfile.TemporaryDirectory() as temp_dir:
        # Extract backup
        with zipfile.ZipFile(backup_record.backup_file_path, 'r') as zipf:
            zipf.extractall(temp_dir)
        
        # Restore database
        db_json_file = os.path.join(temp_dir, "database.json")
        if os.path.exists(db_json_file):
            restore_database_from_json(backup_record.company_id, db_json_file)
        
        # Restore attachments
        attachments_dir = os.path.join(temp_dir, "attachments")
        if os.path.exists(attachments_dir):
            restore_attachments(backup_record.company_id, attachments_dir)
    
    # Update backup record
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

def restore_database_from_json(company_id: str, json_file: str):
    """Restore database from JSON export"""
    from customer_models import (
        CompanyUser, Client, Order, StockItem, Invoice, InvoiceItem,
        Estimate, EstimateItem, PurchaseInvoice, PurchaseInvoiceItem,
        StockPurchaseHistory, CashTransaction, BankAccount, BankTransaction,
        Loan, LoanRepayment
    )
    
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Verify company ID matches
    if data["company_id"] != company_id:
        raise Exception(f"Backup is for company {data['company_id']}, cannot restore to {company_id}")
    
    cdb = get_customer_session(company_id)
    
    # Define order for clearing data (child tables first, then parents)
    # For child tables without company_id, we need to delete through parent relationship
    clear_order = [
        ("loan_repayments", LoanRepayment, "loan_id", Loan),
        ("bank_transactions", BankTransaction, "bank_account_id", BankAccount),
        ("stock_purchase_history", StockPurchaseHistory, "purchase_invoice_id", PurchaseInvoice),
        ("purchase_invoice_items", PurchaseInvoiceItem, "purchase_invoice_id", PurchaseInvoice),
        ("invoice_items", InvoiceItem, "invoice_id", Invoice),
        ("estimate_items", EstimateItem, "estimate_id", Estimate),
    ]
    
    # Clear child tables first (by joining with parent)
    for table_name, model, fk_name, parent_model in clear_order:
        # Delete records where parent belongs to this company
        cdb.query(model).filter(
            getattr(model, fk_name).in_(
                cdb.query(parent_model.id).filter(parent_model.company_id == company_id)
            )
        ).delete(synchronize_session=False)
    
    # Clear parent tables (these have company_id directly)
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
    
    # Restore data in correct order (parents first, then children)
    restore_order = [
        ("company_users", CompanyUser),
        ("clients", Client),
        ("stock_items", StockItem),
        ("bank_accounts", BankAccount),
        ("loans", Loan),
        ("invoices", Invoice),
        ("estimates", Estimate),
        ("purchase_invoices", PurchaseInvoice),
        ("orders", Order),
        ("invoice_items", InvoiceItem),
        ("estimate_items", EstimateItem),
        ("purchase_invoice_items", PurchaseInvoiceItem),
        ("stock_purchase_history", StockPurchaseHistory),
        ("cash_transactions", CashTransaction),
        ("bank_transactions", BankTransaction),
        ("loan_repayments", LoanRepayment),
    ]
    
    for table_name, model in restore_order:
        if table_name in data["tables"]:
            for record_data in data["tables"][table_name]:
                # Remove id to let DB auto-generate
                record_data.pop("id", None)
                # Convert date strings back to date objects
                for key, value in record_data.items():
                    if isinstance(value, str):
                        if "date" in key.lower() or key.endswith("_date"):
                            try:
                                record_data[key] = datetime.fromisoformat(value).date()
                            except:
                                pass
                        elif "created_at" in key.lower() or "updated_at" in key.lower():
                            try:
                                record_data[key] = datetime.fromisoformat(value)
                            except:
                                pass
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
        dst = os.path.join(uploads_dir, filename)
        shutil.copy2(src, dst)

def delete_backup(backup_id: str) -> bool:
    """Delete a backup file and its record"""
    from platform_models import BackupRecord
    from app import db
    
    backup_record = BackupRecord.query.filter_by(backup_id=backup_id).first()
    if not backup_record:
        return False
    
    # Delete physical file
    if os.path.exists(backup_record.backup_file_path):
        os.remove(backup_record.backup_file_path)
    
    # Delete record
    db.session.delete(backup_record)
    db.session.commit()
    
    return True

def upload_backup_to_cloud(backup_id: str, destination: str, config: Dict[str, Any]) -> bool:
    """Upload backup to cloud storage"""
    from platform_models import BackupRecord
    from app import db
    
    backup_record = BackupRecord.query.filter_by(backup_id=backup_id).first()
    if not backup_record:
        raise Exception("Backup not found")
    
    try:
        if destination == "s3":
            # Upload to AWS S3
            s3_client = boto3.client(
                's3',
                aws_access_key_id=config.get('access_key'),
                aws_secret_access_key=config.get('secret_key'),
                region_name=config.get('region', 'us-east-1')
            )
            bucket_name = config.get('bucket')
            key = f"backups/{backup_id}.zip"
            s3_client.upload_file(backup_record.backup_file_path, bucket_name, key)
            backup_record.cloud_location = f"s3://{bucket_name}/{key}"
            
        elif destination == "gcs":
            # Upload to Google Cloud Storage
            client = storage.Client.from_service_account_json(config.get('credentials_file'))
            bucket = client.bucket(config.get('bucket'))
            blob = bucket.blob(f"backups/{backup_id}.zip")
            blob.upload_from_filename(backup_record.backup_file_path)
            backup_record.cloud_location = f"gs://{config.get('bucket')}/backups/{backup_id}.zip"
            
        elif destination == "ftp":
            # Upload via FTP/SFTP
            transport = paramiko.Transport((config.get('host'), int(config.get('port', 22))))
            transport.connect(username=config.get('username'), password=config.get('password'))
            sftp = paramiko.SFTPClient.from_transport(transport)
            remote_path = f"{config.get('path', '/')}/{backup_id}.zip"
            sftp.put(backup_record.backup_file_path, remote_path)
            sftp.close()
            transport.close()
            backup_record.cloud_location = f"ftp://{config.get('host')}{remote_path}"
        
        backup_record.cloud_backup = True
        db.session.commit()
        return True
        
    except Exception as e:
        raise Exception(f"Cloud upload failed: {str(e)}")

def download_backup_from_cloud(backup_id: str) -> str:
    """Download backup from cloud storage"""
    from platform_models import BackupRecord
    from app import db
    
    backup_record = BackupRecord.query.filter_by(backup_id=backup_id).first()
    if not backup_record or not backup_record.cloud_location:
        raise Exception("Cloud backup not found")
    
    local_path = os.path.join(BACKUP_DIR, f"{backup_id}.zip")
    
    if backup_record.cloud_location.startswith("s3://"):
        # Download from S3
        import re
        match = re.match(r"s3://([^/]+)/(.+)", backup_record.cloud_location)
        if match:
            bucket, key = match.groups()
            s3_client = boto3.client('s3')
            s3_client.download_file(bucket, key, local_path)
            
    elif backup_record.cloud_location.startswith("gs://"):
        # Download from GCS
        import re
        match = re.match(r"gs://([^/]+)/(.+)", backup_record.cloud_location)
        if match:
            bucket, key = match.groups()
            client = storage.Client()
            bucket_obj = client.bucket(bucket)
            blob = bucket_obj.blob(key)
            blob.download_to_filename(local_path)
    
    return local_path
