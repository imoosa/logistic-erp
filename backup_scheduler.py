"""
backup_scheduler.py
Background scheduler for automatic backups
"""

import threading
import time
from datetime import datetime, timedelta
from app import app, db
from platform_models import BackupSchedule, BackupRecord
from backup_utils import create_company_backup, delete_backup

def run_scheduled_backups():
    """Background thread to run scheduled backups"""
    while True:
        with app.app_context():
            now = datetime.now()
            
            # Find schedules that need to run
            schedules = BackupSchedule.query.filter(
                BackupSchedule.is_active == True,
                BackupSchedule.next_backup <= now
            ).all()
            
            for schedule in schedules:
                try:
                    # Create backup
                    backup_info = create_company_backup(
                        schedule.company_id, 
                        include_attachments=True
                    )
                    
                    # Upload to cloud if enabled
                    if schedule.upload_to_cloud and schedule.company.backup_schedule:
                        # Get cloud config from company settings
                        from backup_utils import upload_backup_to_cloud
                        # Implement cloud config retrieval from company settings
                        pass
                    
                    # Update schedule
                    schedule.last_backup = now
                    
                    # Calculate next backup directly here instead of calling external function
                    from datetime import timedelta
                    hour, minute = map(int, schedule.time_of_day.split(':'))
                    next_date = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    
                    if schedule.frequency == "daily":
                        if next_date <= now:
                            next_date += timedelta(days=1)
                    elif schedule.frequency == "weekly":
                        days_ahead = 6 - now.weekday()
                        next_date = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
                        if next_date <= now:
                            next_date += timedelta(days=7)
                    elif schedule.frequency == "monthly":
                        next_date = now.replace(day=1, hour=hour, minute=minute, second=0, microsecond=0)
                        if next_date <= now:
                            if next_date.month == 12:
                                next_date = next_date.replace(year=next_date.year + 1, month=1)
                            else:
                                next_date = next_date.replace(month=next_date.month + 1)
                    
                    schedule.next_backup = next_date
                    
                    # Clean up old backups
                    cleanup_old_backups(schedule.company_id, schedule.retention_days)
                    
                    db.session.commit()
                    
                except Exception as e:
                    print(f"Backup failed for {schedule.company_id}: {str(e)}")
            
        # Sleep for 1 hour before checking again
        time.sleep(3600)

def cleanup_old_backups(company_id: str, retention_days: int):
    """Delete backups older than retention days"""
    cutoff_date = datetime.now() - timedelta(days=retention_days)
    
    old_backups = BackupRecord.query.filter(
        BackupRecord.company_id == company_id,
        BackupRecord.backup_date < cutoff_date
    ).all()
    
    for backup in old_backups:
        delete_backup(backup.backup_id)

def start_backup_scheduler():
    """Start the backup scheduler in a background thread"""
    scheduler_thread = threading.Thread(target=run_scheduled_backups, daemon=True)
    scheduler_thread.start()
    print("Backup scheduler started")
