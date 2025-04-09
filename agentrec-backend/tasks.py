# agentrec-backend/tasks.py
from .celery_app import celery # Import celery instance from celery_app.py
# Import models using relative path
from .models import db, ReconciliationJob, JobStatus, ReconciliationType, DataSourceMapping
# Import main processing function
from .services.reconciliation_service import process_reconciliation
# Import factory to create app context
from . import create_app
from datetime import datetime, timezone
import logging
import os

# --- Imports needed for loading KB IN THE TASK ---
from langchain.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import InMemoryVectorStore # Corrected import path
# --- Import Embeddings from ai_service ---
from .services.ai_service import embeddings # Need the initialized embeddings instance

logging.basicConfig(level=logging.INFO)


# Custom Exception for Reconciliation Task Errors
class ReconciliationError(Exception):
    pass


# The @celery.task decorator uses the imported instance
@celery.task(bind=True, name='tasks.run_reconciliation_task', throws=(ReconciliationError,)) # Define expected exception
def run_reconciliation_task(self, job_id):
    """Background task using type-specific config stored in DB."""
    app = create_app() # Create Flask app instance for context
    with app.app_context(): # Use its context for DB access etc.
        job = None # Initialize job to None
        try:
            # Eager load related objects needed in the task
            job = ReconciliationJob.query.options(
                db.joinedload(ReconciliationJob.reconciliation_type), # Eager load the job's type
                db.joinedload(ReconciliationJob.source_mapping),     # Eager load the job's source mapping
                db.joinedload(ReconciliationJob.target_mapping)      # Eager load the job's target mapping
            ).get(job_id)

            if not job:
                logging.error(f"Job {job_id} not found in database.")
                # Raise an exception to mark task failure if job not found
                raise ReconciliationError(f"Job ID {job_id} not found.")

            if not job.reconciliation_type:
                 raise ReconciliationError(f"Reconciliation Type missing for Job {job_id}.")
            if not job.source_mapping or not job.target_mapping:
                 raise ReconciliationError(f"Mappings missing for Job {job_id}.")

            # --- Load Type-Specific Config from DB ---
            recon_type = job.reconciliation_type
            source_map_config = {'id': job.source_mapping.id, 'column_mappings': job.source_mapping.column_mappings, 'date_format_string': job.source_mapping.date_format_string}
            target_map_config = {'id': job.target_mapping.id, 'column_mappings': job.target_mapping.column_mappings, 'date_format_string': job.target_mapping.date_format_string}
            candidate_strategy = recon_type.candidate_selection_strategy
            kb_content_str = recon_type.knowledge_base_content # Get KB content string
            prompt_template_str = recon_type.ai_prompt_template # Get prompt string
            # ---

            # --- Initialize KB Retriever for this task run ---
            kb_retriever = None
            if not embeddings:
                 raise ReconciliationError("AI Embeddings Service unavailable.")
            if not kb_content_str:
                 raise ReconciliationError(f"KB content missing for Recon Type {recon_type.id}")

            try:
                logging.info(f"Initializing KB Retriever from content for Job {job_id}...")
                text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
                docs = text_splitter.create_documents([kb_content_str])
                if not docs: raise ValueError("KB content generated no documents.")
                logging.info(f"Splitting KB content into {len(docs)} documents for Job {job_id}.")
                vectorstore = InMemoryVectorStore.from_documents(docs, embeddings)
                kb_retriever = vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 4})
                logging.info(f"KB Retriever initialized for Job {job_id}.")
            except Exception as e_kb:
                logging.error(f"Error initializing KB Retriever for job {job_id}: {e_kb}", exc_info=True)
                raise ReconciliationError(f"Failed to load/index KB: {e_kb}")
            # ---

            # --- Validate Prompt Template ---
            if not prompt_template_str or "{context}" not in prompt_template_str or "{format_instructions}" not in prompt_template_str:
                raise ReconciliationError(f"Invalid Prompt Template for Recon Type {recon_type.id}")
            # ---

            # --- Update Job Status to Processing ---
            job.status = JobStatus.PROCESSING
            job.celery_task_id = self.request.id # Store Celery task ID
            db.session.commit() # Commit status change before long process
            logging.info(f"Job {job_id} status set to PROCESSING.")
            # ---

            # --- Execute Reconciliation Core Logic ---
            # This function now needs to handle its own DB session scope or be passed one
            # For simplicity, we assume it uses the global db.session within the task's app_context
            results = process_reconciliation(
                job_id=job.id,
                source_file_path=job.source_file,
                target_file_path=job.target_file,
                source_map_config=source_map_config,
                target_map_config=target_map_config,
                kb_retriever=kb_retriever,
                prompt_template_str=prompt_template_str,
                candidate_strategy=candidate_strategy
            )
            # ---

            # --- Final Update on Success ---
            # Re-fetch job to ensure we have latest state before final update
            job_final = ReconciliationJob.query.get(job_id)
            if job_final:
                job_final.status = JobStatus.COMPLETED
                job_final.completed_at = datetime.now(timezone.utc)
                job_final.results_summary = results.get('summary', {}) # Get summary from result
                db.session.commit()
                logging.info(f"Successfully completed reconciliation for Job ID: {job_id}")
            else:
                 # This case should be rare if the initial fetch worked
                 logging.error(f"Job {job_id} disappeared before final completion commit.")
            # ---

        except (ReconciliationError, Exception) as e:
            # Catch errors from validation, KB loading, or process_reconciliation
            logging.error(f"Reconciliation Task failed for Job ID {job_id}: {e}", exc_info=True)
            # Ensure rollback happens within the context
            db.session.rollback()
            # Update job status to FAILED
            job_error = ReconciliationJob.query.get(job_id) # Re-fetch job
            if job_error:
                 job_error.status = JobStatus.FAILED
                 # Try to get summary from process_reconciliation's exception handling, otherwise basic error
                 error_summary = getattr(e, 'summary', None) or job_error.results_summary or {}
                 if 'error' not in error_summary: error_summary['error'] = f'Task failed: {e}'
                 job_error.results_summary = error_summary
                 job_error.completed_at = datetime.now(timezone.utc) # Mark completion time even on failure
                 db.session.commit()
                 logging.warning(f"Job ID {job_id} marked as FAILED.")
            else:
                 logging.error(f"Job {job_id} not found after error, cannot mark as FAILED.")

            # Re-raise the exception to make Celery aware the task failed
            raise e