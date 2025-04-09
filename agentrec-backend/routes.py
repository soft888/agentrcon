# agentrec-backend/routes.py
from flask import Blueprint, request, jsonify, current_app
# Use relative imports for models and tasks
from .models import db, ReconciliationJob, JobStatus, ExceptionLog, ReconciliationResultItem, DataSourceMapping, ReconciliationType, MappingSourceType
from .tasks import run_reconciliation_task
from sqlalchemy import desc, or_
import logging
import os, json
from werkzeug.utils import secure_filename
from datetime import datetime

bp = Blueprint('api', __name__, url_prefix='/api')
logging.basicConfig(level=logging.INFO)

# --- Endpoint to get available reconciliation types ---
# --- GET Reconciliation Types (Existing) ---
@bp.route('/reconciliation_types', methods=['GET'])
def get_reconciliation_types():
    # ... (keep existing implementation) ...
    try:
        types = ReconciliationType.query.filter_by(is_active=True).order_by(ReconciliationType.name).all()
        types_data = [{"id": t.id, "name": t.name, "description": t.description} for t in types]
        return jsonify(types_data)
    except Exception as e:
        logging.error(f"Error fetching reconciliation types: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve reconciliation types"}), 500


# --- ADD NEW: POST Reconciliation Type ---
@bp.route('/reconciliation_types', methods=['POST'])
def create_reconciliation_type():
    """Creates a new reconciliation type configuration."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON payload required"}), 400

    # Basic Validation
    required_fields = ['name', 'knowledge_base_content', 'ai_prompt_template']
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields:
        return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

    # Check for duplicate name
    # Check for duplicate name using filter()
    if ReconciliationType.query.filter(ReconciliationType.name == data['name']).first(): # <-- Use .filter() and Model.attribute
        return jsonify({"error": f"Reconciliation Type name '{data['name']}' already exists."}), 409

    try:
        new_type = ReconciliationType(
            name=data['name'],
            description=data.get('description'), # Optional field
            knowledge_base_content=data['knowledge_base_content'],
            ai_prompt_template=data['ai_prompt_template'],
            candidate_selection_strategy=data.get('candidate_selection_strategy', 'default_date_amount'), # Use default if not provided
            is_active=data.get('is_active', True) # Default to active
        )
        db.session.add(new_type)
        db.session.commit()
        logging.info(f"Created new Reconciliation Type: ID={new_type.id}, Name='{new_type.name}'")
        # Return the created object (useful for the frontend)
        return jsonify({
            "id": new_type.id,
            "name": new_type.name,
            "description": new_type.description,
            "is_active": new_type.is_active
            # Avoid sending back large content fields unless necessary
        }), 201 # 201 Created status

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating reconciliation type: {e}", exc_info=True)
        return jsonify({"error": "Failed to create reconciliation type"}), 500
# --- END ADD ---

# --- Endpoint to get available mappings, optionally filtered ---

@bp.route('/mappings', methods=['GET'])
def get_mappings():
    """Returns a list of data source mappings, optionally filtered."""
    try:
        source_type_filter_str = request.args.get('source_type') # 'source' or 'target'
        recon_type_id_filter = request.args.get('reconciliationTypeId', type=int)

        query = DataSourceMapping.query

        if source_type_filter_str:
            try:
                 source_type_enum = MappingSourceType(source_type_filter_str)
                 query = query.filter(DataSourceMapping.source_type == source_type_enum)
            except ValueError:
                 return jsonify({"error": f"Invalid source_type filter: {source_type_filter_str}"}), 400

        if recon_type_id_filter:
             # Use or_() for OR condition in SQLAlchemy filter
             query = query.filter( or_(
                 DataSourceMapping.reconciliation_type_id == recon_type_id_filter,
                 DataSourceMapping.reconciliation_type_id == None
             ) )

        mappings = query.order_by(DataSourceMapping.mapping_name).all()
        # Return detailed mapping info if needed, or just id/name/type
        mappings_data = [{
            "id": m.id,
            "name": m.mapping_name,
            "type": m.source_type.value,
            "reconciliationTypeId": m.reconciliation_type_id, # Include associated type ID
             # Optionally include column mappings for display/editing later?
             # "columnMappings": m.column_mappings,
             # "dateFormat": m.date_format_string
         } for m in mappings]
        return jsonify(mappings_data)
    except Exception as e:
        logging.error(f"Error fetching mappings: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve mappings"}), 500

@bp.route('/mappings', methods=['POST'])
def create_mapping():
    """Creates a new data source mapping configuration."""
    data = request.get_json()
    if not data: return jsonify({"error": "Invalid JSON payload required"}), 400

    required_fields = ['mapping_name', 'source_type', 'column_mappings']
    missing_fields = [field for field in required_fields if field not in data or not data.get(field)]
    if missing_fields: return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

    # Validate source_type
    try:
        source_type_enum = MappingSourceType(data['source_type'])
    except ValueError:
        return jsonify({"error": f"Invalid source_type value: '{data['source_type']}'. Must be 'source' or 'target'."}), 400

    # Validate column_mappings is a dictionary
    column_mappings_data = data['column_mappings']
    if not isinstance(column_mappings_data, dict) or not column_mappings_data:
         # Try parsing if it came as a string
         if isinstance(column_mappings_data, str):
             try:
                 column_mappings_data = json.loads(column_mappings_data)
                 if not isinstance(column_mappings_data, dict) or not column_mappings_data:
                      raise ValueError("Parsed column_mappings is not a non-empty dictionary.")
             except (json.JSONDecodeError, ValueError) as e:
                 return jsonify({"error": f"Invalid column_mappings format. Must be a non-empty JSON object (dictionary). Error: {e}"}), 400
         else:
              return jsonify({"error": "Invalid column_mappings format. Must be a non-empty JSON object (dictionary)."}), 400


    # Check for duplicate name
    if DataSourceMapping.query.filter(DataSourceMapping.mapping_name == data['mapping_name']).first():
        return jsonify({"error": f"Mapping name '{data['mapping_name']}' already exists."}), 409

    # Optional: Validate associated recon type ID exists if provided
    recon_type_id = data.get('reconciliation_type_id')
    if recon_type_id and not ReconciliationType.query.get(recon_type_id):
        return jsonify({"error": f"Invalid reconciliation_type_id: {recon_type_id}"}), 400

    try:
        new_mapping = DataSourceMapping(
            mapping_name=data['mapping_name'],
            source_type=source_type_enum,
            column_mappings=column_mappings_data, # Store the validated dictionary
            date_format_string=data.get('date_format_string'), # Optional
            reconciliation_type_id=recon_type_id # Optional
        )
        db.session.add(new_mapping)
        db.session.commit()
        logging.info(f"Created new DataSourceMapping: ID={new_mapping.id}, Name='{new_mapping.mapping_name}'")
        # Return the created mapping object
        return jsonify({
            "id": new_mapping.id,
            "name": new_mapping.mapping_name,
            "type": new_mapping.source_type.value,
            "reconciliationTypeId": new_mapping.reconciliation_type_id
        }), 201

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating mapping: {e}", exc_info=True)
        return jsonify({"error": "Failed to create mapping"}), 500


# --- Upload Endpoint (Requires Type and Mapping IDs) ---
@bp.route('/reconciliations/upload', methods=['POST'])
def upload_files():
    """Handles file uploads and creates a new reconciliation job."""
    if 'sourceFile' not in request.files or 'targetFile' not in request.files:
        return jsonify({"error": "Source and target files required"}), 400
    
    reconciliation_type_id = request.form.get('reconciliation_type_id', type=int)
    source_mapping_id = request.form.get('source_mapping_id', type=int)
    target_mapping_id = request.form.get('target_mapping_id', type=int)
    
    if not reconciliation_type_id:
        return jsonify({"error": "Reconciliation Type ID required"}), 400
    if not source_mapping_id:
        return jsonify({"error": "Source Mapping ID required"}), 400
    if not target_mapping_id:
        return jsonify({"error": "Target Mapping ID required"}), 400
    
    source_file = request.files['sourceFile']
    target_file = request.files['targetFile']
    if source_file.filename == '' or target_file.filename == '':
        return jsonify({"error": "No selected file(s)"}), 400

    # Validate DB objects exist
    recon_type = ReconciliationType.query.get(reconciliation_type_id)
    source_map = DataSourceMapping.query.get(source_mapping_id)
    target_map = DataSourceMapping.query.get(target_mapping_id)
    
    if not recon_type:
        return jsonify({"error": "Invalid Reconciliation Type"}), 400
    if not source_map or source_map.source_type != MappingSourceType.SOURCE:
        return jsonify({"error": "Invalid source mapping"}), 400
    if not target_map or target_map.source_type != MappingSourceType.TARGET:
        return jsonify({"error": "Invalid target mapping"}), 400

    try:
        ts = datetime.now().strftime('%Y%m%d%H%M%S')
        upload_folder = current_app.config['UPLOAD_FOLDER']
        source_filename = secure_filename(f"{ts}_r{reconciliation_type_id}_s{source_mapping_id}_{source_file.filename}")
        target_filename = secure_filename(f"{ts}_r{reconciliation_type_id}_t{target_mapping_id}_{target_file.filename}")
        source_path = os.path.join(upload_folder, source_filename)
        target_path = os.path.join(upload_folder, target_filename)
        
        source_file.save(source_path)
        target_file.save(target_path)
        
        new_job = ReconciliationJob(
            reconciliation_type_id=reconciliation_type_id,
            source_file=source_path,
            target_file=target_path,
            source_mapping_id=source_mapping_id,
            target_mapping_id=target_mapping_id
        )
        
        db.session.add(new_job)
        db.session.commit()
        logging.info(f"Created Job ID: {new_job.id} Type: {reconciliation_type_id}")
        return jsonify({"message": "Files uploaded successfully", "jobId": new_job.id}), 201
    except Exception as e:
        db.session.rollback()
        logging.error(f"Upload Error: {e}", exc_info=True)
        return jsonify({"error": "File upload failed"}), 500

# --- /run endpoint ---
@bp.route('/reconciliations/<int:job_id>/run', methods=['POST'])
def run_reconciliation(job_id):
    try:
        job = ReconciliationJob.query.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        if job.status not in [JobStatus.PENDING, JobStatus.FAILED]:
            return jsonify({"error": f"Job already {job.status.value}"}), 400
        
        task = run_reconciliation_task.delay(job.id)
        job.status = JobStatus.PENDING
        job.celery_task_id = task.id
        db.session.commit()
        
        logging.info(f"Dispatched Task {task.id} for Job {job_id}")
        return jsonify({"message": "Task started", "jobId": job.id, "taskId": task.id}), 202
    except Exception as e:
        logging.error(f"Error dispatching task for job {job_id}: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "Failed to start task"}), 500

# --- /results endpoint ---
@bp.route('/reconciliations/results', methods=['GET'])
def get_reconciliation_results():
    try:
        job_id_filter = request.args.get('jobId', type=int)
        query_job_id = None

        if job_id_filter:
            job_to_show = ReconciliationJob.query.get(job_id_filter)
            if job_to_show:
                query_job_id = job_id_filter
        else:
            latest_completed_job = ReconciliationJob.query.filter_by(
                status=JobStatus.COMPLETED
            ).order_by(desc(ReconciliationJob.completed_at)).first()
            query_job_id = latest_completed_job.id if latest_completed_job else None

        if not query_job_id:
            return jsonify({
                "items": [],
                "total_items": 0,
                "current_page": 1,
                "per_page": 10,
                "total_pages": 0,
                "jobIdShown": None
            })

        logging.info(f"Fetching results for Job ID: {query_job_id}")
        query = ReconciliationResultItem.query.filter_by(job_id=query_job_id)
        
        status_filter = request.args.get('status')
        if status_filter:
            query = query.filter(ReconciliationResultItem.status == status_filter)
        
        query = query.order_by(ReconciliationResultItem.date.desc(), ReconciliationResultItem.id.asc())
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('page_size', 10, type=int)
        
        pagination_obj = query.paginate(page=page, per_page=per_page, error_out=False)
        results_data = [item.to_dict() for item in pagination_obj.items]
        
        return jsonify({
            "items": results_data,
            "total_items": pagination_obj.total,
            "current_page": page,
            "per_page": per_page,
            "total_pages": pagination_obj.pages,
            "jobIdShown": query_job_id
        })
    except Exception as e:
        logging.error(f"Error fetching reconciliation results: {e}", exc_info=True)
        return jsonify({"error": "Failed"}), 500

# --- /status endpoint ---
@bp.route('/reconciliations/<int:job_id>/status', methods=['GET'])
def get_job_status(job_id):
    try:
        job = ReconciliationJob.query.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify({
            "jobId": job.id,
            "status": job.status.value,
            "createdAt": job.created_at.isoformat() if job.created_at else None,
            "completedAt": job.completed_at.isoformat() if job.completed_at else None,
            "summary": job.results_summary
        }), 200
    except Exception as e:
        logging.error(f"Error fetching status job {job_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed"}), 500

# --- Dashboard Stats (Placeholder) ---
@bp.route('/dashboard/stats', methods=['GET'])
def get_dashboard_stats_placeholder():
    return jsonify({
        "total_transactions": 0,
        "auto_reconciled_percent": 0,
        "pending_exceptions": 0,
        "high_priority_exceptions": 0
    })

# --- Exceptions List (Placeholder Pagination/Filtering) ---
@bp.route('/exceptions', methods=['GET'])
def get_exceptions():
    try:
        query = ExceptionLog.query  # Add filters based on request.args
        exceptions = query.order_by(desc(ExceptionLog.created_at)).all()
        exceptions_data = [{
            "id": ex.exception_id_display,
            "date": ex.created_at.strftime('%Y-%m-%d'),
            "description": (ex.details or {}).get('title', ex.exception_type),
            "amount": str((ex.details or {}).get('amount', 'N/A')),
            "type": ex.exception_type,
            "priority": ex.priority,
            "selected": False
        } for ex in exceptions]
        return jsonify(exceptions_data)
    except Exception as e:
        logging.error(f"Error fetching exceptions: {e}", exc_info=True)
        return jsonify({"error": "Failed"}), 500

# --- Exception Detail ---
@bp.route('/exceptions/<string:exception_id>', methods=['GET'])
def get_exception_detail(exception_id):
    try:
        exception = ExceptionLog.query.filter_by(exception_id_display=exception_id).first()
        if not exception:
            return jsonify({"error": "Exception not found"}), 404
        
        details = exception.details or {}
        exception_data = {
            "id": exception.exception_id_display,
            "createdDate": exception.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            "priority": exception.priority or 'N/A',
            "exceptionTitle": details.get('title', f"E: {exception.exception_type}"),
            "exceptionType": exception.exception_type or 'Unknown',
            "transaction": details.get('transaction', {}),
            "discrepancy": details.get('discrepancy', {"bank": {}, "erp": {}}),
            "aiAnalysis": details.get('ai_reason', 'N/A')
        }
        return jsonify(exception_data)
    except Exception as e:
        logging.error(f"Error fetching details for exception {exception_id}: {e}", exc_info=True)
    except Exception as e: logging.error(f"Error fetching details for exception {exception_id}: {e}", exc_info=True); return jsonify({"error": "Failed"}), 500
