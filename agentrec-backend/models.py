# agentrec-backend/models.py
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
import enum
import json

from . import db # Relative import for factory pattern

# --- Enums ---
class JobStatus(enum.Enum):
    PENDING = 'PENDING'
    PROCESSING = 'PROCESSING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'

class MappingSourceType(enum.Enum):
    SOURCE = 'source'
    TARGET = 'target'
# --- END Enums ---

# --- Models ---

class ReconciliationType(db.Model):
    __tablename__ = 'reconciliation_type'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    knowledge_base_content = db.Column(db.Text, nullable=False)
    ai_prompt_template = db.Column(db.Text, nullable=False)
    candidate_selection_strategy = db.Column(db.String(50), default='default_date_amount')
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Define relationships using db.backref in the *other* models
    # jobs = db.relationship(...) # REMOVED from here
    # data_source_mappings = db.relationship(...) # REMOVED from here

    # --- ADD extend_existing=True ---
    __table_args__ = {'extend_existing': True}
    # --- END ADD ---

    def __repr__(self):
        return f'<ReconciliationType {self.id} - {self.name}>'

class DataSourceMapping(db.Model):
    # ... (DataSourceMapping definition as before) ...
    __tablename__ = 'data_source_mapping'
    id = db.Column(db.Integer, primary_key=True)
    mapping_name = db.Column(db.String(150), nullable=False, unique=True)
    source_type = db.Column(db.Enum(MappingSourceType, name='mapping_source_type_enum', native_enum=False), nullable=False)
    column_mappings = db.Column(db.JSON, nullable=False)
    date_format_string = db.Column(db.String(50), nullable=True)
    reconciliation_type_id = db.Column(db.Integer, db.ForeignKey('reconciliation_type.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    __table_args__ = {'extend_existing': True}

    def __repr__(self): return f'<DataSourceMapping {self.id} - {self.mapping_name} ({self.source_type.name})>'


class ReconciliationJob(db.Model):
    __tablename__ = 'reconciliation_job'
    id = db.Column(db.Integer, primary_key=True)
    # Foreign Key linking to the type
    reconciliation_type_id = db.Column(db.Integer, db.ForeignKey('reconciliation_type.id'), nullable=False, index=True)
    
    # ... other columns: source_file, target_file, mappings_ids, status, etc ...
    source_file = db.Column(db.String(255), nullable=False)
    target_file = db.Column(db.String(255), nullable=False)
    source_mapping_id = db.Column(db.Integer, db.ForeignKey('data_source_mapping.id'), nullable=False, index=True)
    target_mapping_id = db.Column(db.Integer, db.ForeignKey('data_source_mapping.id'), nullable=False, index=True)
    status = db.Column(db.Enum(JobStatus, name='jobstatus'), default=JobStatus.PENDING, nullable=False)
    celery_task_id = db.Column(db.String(100), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    results_summary = db.Column(db.JSON, nullable=True)

    # --- DEFINE RELATIONSHIP HERE with backref to create ReconciliationType.jobs ---
    reconciliation_type = db.relationship('ReconciliationType', backref=db.backref('jobs', lazy='dynamic'))
    # ---

    # Relationships to exceptions and results (keep as is)
    exceptions = db.relationship('ExceptionLog', backref='job', lazy=True, cascade="all, delete-orphan")
    result_items = db.relationship('ReconciliationResultItem', backref='job', lazy=True, cascade="all, delete-orphan")
    # Relationships to mappings (keep as is)
    source_mapping = db.relationship('DataSourceMapping', foreign_keys=[source_mapping_id])
    target_mapping = db.relationship('DataSourceMapping', foreign_keys=[target_mapping_id])

    __table_args__ = {'extend_existing': True}

    def __repr__(self): status_name = self.status.name if self.status else 'UNKNOWN'; return f'<ReconciliationJob {self.id} - Type: {self.reconciliation_type_id} - Status: {status_name}>'

class ExceptionLog(db.Model):
    __tablename__ = 'exception_log'
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('reconciliation_job.id'), nullable=False, index=True)
    exception_id_display = db.Column(db.String(50), unique=True, nullable=False, index=True)
    exception_type = db.Column(db.String(100), nullable=False, index=True)
    priority = db.Column(db.String(20), index=True)
    status = db.Column(db.String(50), default='Open', nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    details = db.Column(db.JSON, nullable=True)

    __table_args__ = {'extend_existing': True}

    def __repr__(self):
        return f'<ExceptionLog {self.exception_id_display} ({self.exception_type})>'

class ReconciliationResultItem(db.Model):
    __tablename__ = 'reconciliation_result_item'
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('reconciliation_job.id'), nullable=False, index=True)
    display_id = db.Column(db.String(100), index=True)
    date = db.Column(db.Date, index=True)
    description = db.Column(db.Text)
    amount = db.Column(db.Numeric(15, 2))
    status = db.Column(db.String(50), nullable=False, index=True)
    action = db.Column(db.String(50))
    details = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = {'extend_existing': True}

    def to_dict(self):
        amount_str = str(self.amount) if self.amount is not None else None
        date_str = self.date.strftime('%Y-%m-%d') if self.date else None
        details_data = self.details or {}
        return {
            "id": self.display_id, "date": date_str, "description": self.description,
            "amount": amount_str, "status": self.status, "action": self.action,
            "exception_id_display": details_data.get("exception_id_display", None), }

    def __repr__(self):
        return f'<ReconciliationResultItem {self.id} for Job {self.job_id} ({self.status})>'