
# app.py
import os
import sys
import logging
# Add the project root directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))


from flask import Flask, Blueprint, request, jsonify
from flask_cors import CORS # <-- Import CORS
from config import Config
from .models import db, ReconciliationJob, JobStatus, ExceptionLog, ReconciliationResultItem # Add Result Item
from .tasks import run_reconciliation_task
from werkzeug.utils import secure_filename
from datetime import datetime
from flask_migrate import Migrate # <-- Make sure this is imported
from sqlalchemy import desc # To order jobs

import logging

app = Blueprint('api', __name__, url_prefix='/api')

# app = Flask(__name__)
# app.config.from_object(Config)

# CORS(app, resources={r"/api/*": {"origins": "http://localhost:3000"}})

# db.init_app(app)
# migrate = Migrate(app, db) # <-- Make sure this line is present and uncommented

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- API Endpoints ---
@app.route('/api/reconciliations/upload', methods=['POST'])
def upload_files():
    if 'sourceFile' not in request.files or 'targetFile' not in request.files:
        return jsonify({"error": "Source and target files are required"}), 400

    source_file = request.files['sourceFile']
    target_file = request.files['targetFile']

    if source_file.filename == '' or target_file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        source_filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_source_{source_file.filename}")
        target_filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_target_{target_file.filename}")

        source_path = os.path.join(app.config['UPLOAD_FOLDER'], source_filename)
        target_path = os.path.join(app.config['UPLOAD_FOLDER'], target_filename)

        source_file.save(source_path)
        target_file.save(target_path)

        # Create Job Entry in DB
        new_job = ReconciliationJob(
            source_file=source_path, # Store full path or relative
            target_file=target_path
            # Add KB file if uploaded
        )
        db.session.add(new_job)
        db.session.commit()

        return jsonify({"message": "Files uploaded successfully", "jobId": new_job.id}), 201

    except Exception as e:
        db.session.rollback()
        # Log error properly
        print(f"Upload Error: {e}")
        return jsonify({"error": "File upload failed"}), 500


@app.route('/api/reconciliations/<int:job_id>/run', methods=['POST'])
def run_reconciliation(job_id):
    job = ReconciliationJob.query.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if job.status not in [JobStatus.PENDING, JobStatus.FAILED]:
         return jsonify({"error": f"Job already {job.status.value}"}), 400

    # Trigger Celery task
    task = run_reconciliation_task.delay(job.id)
    job.status = JobStatus.PENDING # Keep pending until task picks it up
    job.celery_task_id = task.id
    db.session.commit()

    return jsonify({"message": "Reconciliation task started", "jobId": job.id, "taskId": task.id}), 202

@app.route('/api/reconciliations/<int:job_id>/status', methods=['GET'])
def get_job_status(job_id):
    job = ReconciliationJob.query.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # You might also query celery backend for more task details if needed
    # from tasks import celery
    # task_info = celery.AsyncResult(job.celery_task_id)

    return jsonify({
        "jobId": job.id,
        "status": job.status.value,
        "createdAt": job.created_at.isoformat() if job.created_at else None,
        "completedAt": job.completed_at.isoformat() if job.completed_at else None,
        "summary": job.results_summary
    }), 200

# --- Exception Endpoints ---
@app.route('/api/exceptions', methods=['GET'])
def get_exceptions():
    # Add filtering based on request.args (e.g., ?priority=High&status=Open)
    query = ExceptionLog.query
    # Example Filter:
    priority = request.args.get('priority')
    if priority:
        query = query.filter(ExceptionLog.priority == priority)

    exceptions = query.order_by(ExceptionLog.created_at.desc()).all()

    exceptions_data = [{
        "id": ex.exception_id_display, # Use display ID
        "date": ex.created_at.strftime('%Y-%m-%d'), # Format date
        "description": ex.details.get('description', 'N/A') if ex.details else 'N/A', # Get from JSON details
        "amount": str(ex.details.get('amount', 'N/A')) if ex.details else 'N/A', # Get from JSON details
        "type": ex.exception_type,
        "priority": ex.priority,
        "selected": False # Selection is frontend state
        # "status": ex.status # If needed
    } for ex in exceptions]

    return jsonify(exceptions_data)


@app.route('/api/exceptions/<string:exception_id>', methods=['GET'])
def get_exception_detail(exception_id):
    exception = ExceptionLog.query.filter_by(exception_id_display=exception_id).first()
    if not exception:
        return jsonify({"error": "Exception not found"}), 404

    # Prepare data structure similar to what frontend expects
    # This needs mapping from your stored ExceptionLog.details JSON
    details = exception.details or {} # Ensure details is a dict

    exception_data = {
        "id": exception.exception_id_display,
        "createdDate": exception.created_at.strftime('%Y-%m-%d'),
        "priority": exception.priority,
        "exceptionTitle": details.get('title', 'N/A'),
        "exceptionType": exception.exception_type,
        "transaction": details.get('transaction', {}), # Get nested dict
        "discrepancy": details.get('discrepancy', {}), # Get nested dict
        "aiAnalysis": details.get('ai_analysis', 'N/A')
    }

    return jsonify(exception_data)

@app.route('/', methods=['GET'])
def home():
    return "Welcome!"

# --- ADD Placeholder Routes for Missing Endpoints ---

@app.route('/api/dashboard/stats', methods=['GET'])
def get_dashboard_stats_placeholder():
    # TODO: Query actual stats from DB or processing results
    return jsonify({
        "total_transactions": 156354, # Placeholder
        "auto_reconciled_percent": 92.7, # Placeholder
        "pending_exceptions": 84, # Placeholder
        "high_priority_exceptions": 12 # Placeholder
    })

@app.route('/api/reconciliations/results', methods=['GET'])
def get_reconciliation_results():
    try:
        # 1. Find the latest COMPLETED job ID
        latest_completed_job = ReconciliationJob.query.filter_by(
            status=JobStatus.COMPLETED
        ).order_by(
            ReconciliationJob.completed_at.desc() # Order by completion time descending
        ).first()

        if not latest_completed_job:
            # No completed jobs yet, return empty results
            return jsonify({ "items": [], "total_items": 0, "current_page": 1,
                             "per_page": 10, "total_pages": 0 })

        latest_job_id = latest_completed_job.id
        logging.info(f"Fetching results for latest completed job ID: {latest_job_id}")

        # 2. Base query for results of the latest completed job
        query = ReconciliationResultItem.query.filter_by(job_id=latest_job_id)

        # 3. Apply Filters (Example: status)
        status_filter = request.args.get('status')
        if status_filter:
            query = query.filter(ReconciliationResultItem.status == status_filter)

        # TODO: Add more filters based on request.args (dateRange, amountRange, etc.)
        # Remember to parse date strings etc.

        # 4. Apply Sorting (Example: by date)
        query = query.order_by(ReconciliationResultItem.date.desc()) # Default sort

        # 5. Apply Pagination
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('page_size', 10, type=int)
        pagination_obj = query.paginate(page=page, per_page=per_page, error_out=False)

        # 6. Format Output
        results_data = [item.to_dict() for item in pagination_obj.items]

        return jsonify({
            "items": results_data,
            "total_items": pagination_obj.total,
            "current_page": page,
            "per_page": per_page,
            "total_pages": pagination_obj.pages
        })

    except Exception as e:
        logging.error(f"Error fetching reconciliation results: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve reconciliation results"}), 500

# Add endpoints for reports, dashboard stats, resolving exceptions etc.

if __name__ == '__main__':
    # Create DB tables if they don't exist (for SQLite)
    with app.app_context():
        db.create_all()
    app.run(debug=True) # Run in debug mode for development