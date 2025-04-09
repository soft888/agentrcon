# agentrec-backend/services/reconciliation_service.py
# --- Imports ---
from ..models import db, ExceptionLog, ReconciliationResultItem
from .ai_service import get_reconciliation_status, INTERNAL_ID, INTERNAL_DATE, INTERNAL_AMOUNT, INTERNAL_DESC
import logging
import pandas as pd
from decimal import Decimal
from datetime import timedelta
import uuid
import json

logging.basicConfig(level=logging.INFO)

# --- parse_file helper ---
def parse_file(file_path, mapping_config):
    """Parses file using mapping config into list of dicts with internal semantic names."""
    mapping_id = mapping_config.get('id', 'N/A')
    logging.info(f"Parsing file: {file_path} using mapping ID: {mapping_id}")
    
    try:
        column_map = mapping_config.get('column_mappings', {})
        if not column_map:
            raise ValueError(f"No mappings in config ID: {mapping_id}")
            
        original_headers = list(column_map.keys())
        rename_dict = {orig: internal for orig, internal in column_map.items()}
        internal_names_expected = list(rename_dict.values())
        required_internal_names = {INTERNAL_ID, INTERNAL_DATE, INTERNAL_AMOUNT, INTERNAL_DESC}
        
        if not required_internal_names.issubset(internal_names_expected):
            raise ValueError(f"Mapping {mapping_id} must map to: {required_internal_names}")
            
        file_options = {'keep_default_na': False, 'na_values': [''], 'usecols': original_headers}
        original_id_header = next((orig for orig, internal in column_map.items() if internal == INTERNAL_ID), None)
        
        if original_id_header:
            file_options['dtype'] = {original_id_header: str}
            
        if file_path.lower().endswith('.csv'):
            df = pd.read_csv(file_path, **file_options, on_bad_lines='warn', low_memory=False)
        elif file_path.lower().endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file_path, **{k: v for k, v in file_options.items() if k != 'on_bad_lines'})
        else:
            raise ValueError("Unsupported file type")
            
        if df.empty:
            logging.warning(f"File empty: {file_path}")
            return []
            
        df.rename(columns=rename_dict, inplace=True)
        date_format = mapping_config.get('date_format_string')
        df[INTERNAL_DATE] = pd.to_datetime(df[INTERNAL_DATE], format=date_format, errors='coerce').dt.date
        
        def clean_amount(x):
            if pd.isna(x) or x == '':
                return None
            try:
                cleaned = str(x).replace('$', '').replace(',', '').strip()
                if cleaned.startswith('(') and cleaned.endswith(')'):
                    cleaned = '-' + cleaned[1:-1]
                return Decimal(cleaned)
            except (ValueError, TypeError):
                return None
                
        df[INTERNAL_AMOUNT] = df[INTERNAL_AMOUNT].apply(clean_amount)
        df[INTERNAL_ID] = df[INTERNAL_ID].astype(str)
        df[INTERNAL_DESC] = df[INTERNAL_DESC].fillna('').astype(str)
        
        original_rows = len(df)
        # services/reconciliation_service.py (inside parse_file, before dropna)
        logging.debug(f"Data before dropna (Head):\n{df[[INTERNAL_ID, INTERNAL_DATE, INTERNAL_AMOUNT]].head().to_string()}")
        logging.warning(f"NA count in {INTERNAL_ID}: {df[INTERNAL_ID].isna().sum()}")
        logging.warning(f"NA count in {INTERNAL_DATE}: {df[INTERNAL_DATE].isna().sum()}")
        logging.warning(f"NA count in {INTERNAL_AMOUNT}: {df[INTERNAL_AMOUNT].isna().sum()}")
        df.dropna(subset=[INTERNAL_ID, INTERNAL_DATE, INTERNAL_AMOUNT], inplace=True)
        dropped_rows = original_rows - len(df)
        
        if dropped_rows > 0:
            logging.warning(f"Dropped {dropped_rows} rows missing data in {file_path}")
            
        output_columns = [name for name in internal_names_expected if name in df.columns]
        df_clean = df[output_columns]
        logging.info(f"Parsed and mapped {len(df_clean)} rows from {file_path}")
        return df_clean.to_dict('records')
        
    except pd.errors.EmptyDataError as e:
        logging.error(f"Empty data in file {file_path}: {e}")
        raise
    except pd.errors.ParserError as e:
        logging.error(f"Parser error in file {file_path}: {e}")
        raise
    except ValueError as e:
        logging.error(f"Validation error for file {file_path}: {e}")
        raise
    except Exception as e:
        logging.error(f"Error parsing file {file_path} with mapping ID {mapping_id}: {e}", 
                     exc_info=True)
        raise


# --- create_exception_log helper ---
def create_exception_log(job_id, exc_type, priority, details_dict):
    """Creates and adds an ExceptionLog entry to the session."""
    try:
        display_id = f"EXC-{uuid.uuid4().hex[:8].upper()}"
        assigned_priority = priority
        if not assigned_priority:
            exc_type_lower = (exc_type or '').lower()
            if 'mismatch' in exc_type_lower or 'duplicate' in exc_type_lower:
                assigned_priority = 'High'
            elif 'missing' in exc_type_lower:
                assigned_priority = 'Medium'
            else:
                assigned_priority = 'Low'

        # Ensure details are JSON serializable
        try:
            serializable_details = json.loads(json.dumps(details_dict, default=str))
        except (TypeError, ValueError):
            logging.error(f"Failed to serialize exception details for job {job_id}")
            serializable_details = {"error": "Failed to serialize original details"}

        new_exception = ExceptionLog(
            job_id=job_id,
            exception_id_display=display_id,
            exception_type=exc_type or "Unknown",
            priority=assigned_priority,
            status='Open',
            details=serializable_details
        )
        
        db.session.add(new_exception)
        logging.info(f"Prepared ExceptionLog: {display_id} (Type: {exc_type})")
        return display_id
        
    except Exception as e:
        logging.error(f"Error creating ExceptionLog for job {job_id}: {e}", exc_info=True)
        return None

# --- Main Reconciliation Logic ---
def process_reconciliation(job_id, source_file_path, target_file_path,
                            source_map_config, target_map_config,
                            kb_retriever, prompt_template_str, # Receive retriever & prompt
                            candidate_strategy='default_date_amount'):
    """ Uses mappings, specific KB/Prompt via AI service, saves results. """
    logging.info(f"Processing Job ID: {job_id}, Strategy: {candidate_strategy}")
    summary = { 'processed_source': 0, 'processed_target': 0, 'matched_count': 0, 'partial_match_count': 0, 'exceptions_count': 0, 'ai_errors': 0 }
    results_to_add = []

    try:
        source_transactions = parse_file(source_file_path, source_map_config)
        target_transactions = parse_file(target_file_path, target_map_config)
        summary['processed_source'] = len(source_transactions); summary['processed_target'] = len(target_transactions)
        logging.info(f"Parsed {summary['processed_source']} source & {summary['processed_target']} target txns.")

        # Delete old items for this job
        deleted_results = ReconciliationResultItem.query.filter_by(job_id=job_id).delete()
        deleted_exceptions = ExceptionLog.query.filter_by(job_id=job_id).delete()
        if deleted_results > 0 or deleted_exceptions > 0:
             logging.info(f"Deleted old items for Job ID: {job_id}")
             db.session.commit()

        target_used = [False] * len(target_transactions)
        first_exception_found = {}

        # --- Iterate Source ---
        for i, source_tx in enumerate(source_transactions):
            source_internal_id=source_tx[INTERNAL_ID]; source_internal_date=source_tx[INTERNAL_DATE]; source_internal_amount=source_tx[INTERNAL_AMOUNT]; source_internal_desc=source_tx[INTERNAL_DESC]
            final_status_for_source, best_target_idx, best_target_tx = "Unmatched", -1, None
            final_reason, final_exception_type, action = "No suitable match found.", "Missing Transaction (Target)", "Resolve"

            potential_target_indices = []
            # --- Candidate Selection ---
            # (Keep default_date_amount logic or add others based on candidate_strategy)
            if candidate_strategy == 'default_date_amount':
                date_window=timedelta(days=7); amount_tolerance_fixed=Decimal('100.00')
                for j, target_tx in enumerate(target_transactions):
                     if not target_used[j]:
                         target_internal_date=target_tx.get(INTERNAL_DATE); target_internal_amount=target_tx.get(INTERNAL_AMOUNT)
                         if source_internal_date and target_internal_date: date_diff = abs(source_internal_date - target_internal_date);
                         else: date_diff = timedelta(days=999)
                         if date_diff > date_window: continue
                         if source_internal_amount is not None and target_internal_amount is not None: amount_diff = abs(source_internal_amount - target_internal_amount);
                         else: amount_diff = Decimal('inf')
                         if amount_diff > amount_tolerance_fixed: continue
                         potential_target_indices.append(j)
            else: logging.warning(f"Candidate strategy '{candidate_strategy}' not implemented.")
            # ---

            # --- AI Evaluation ---
            if not potential_target_indices: final_status_for_source = "Exception"
            else:
                logging.info(f"Evaluating {len(potential_target_indices)} candidates for Src {source_internal_id}...")
                temp_best_status = "Exception"
                for target_idx in potential_target_indices:
                    target_tx = target_transactions[target_idx]
                    ai_source_input = {k: v for k, v in source_tx.items()}
                    ai_target_input = {k: v for k, v in target_tx.items()}
                    # Call AI with SPECIFIC retriever and prompt
                    ai_result = get_reconciliation_status( ai_source_input, ai_target_input, kb_retriever, prompt_template_str )
                    status = ai_result.get('status', 'Error')
                    if status == 'Error':
                        summary['ai_errors'] += 1
                        if i not in first_exception_found:
                            first_exception_found[i] = {
                                'reason': ai_result.get('reason'),
                                'type': 'AI Processing Error',
                                'target_tx': target_tx
                            }
                        continue
                    if status == 'Matched': final_status_for_source, best_target_idx, best_target_tx, final_reason, final_exception_type, action = "Matched", target_idx, target_tx, ai_result.get('reason'), None, "View"; break
                    elif status == 'Partial Match':
                        if temp_best_status != 'Matched': final_status_for_source, best_target_idx, best_target_tx, final_reason, final_exception_type, action = "Partial Match", target_idx, target_tx, ai_result.get('reason'), ai_result.get('exception_type', 'Partial Issue'), "Review"; temp_best_status = status
                    elif status == 'Exception':
                        if i not in first_exception_found: first_exception_found[i] = {'reason': ai_result.get('reason'), 'type': ai_result.get('exception_type'), 'target_tx': target_tx}

            # --- Process Final Result ---
            exception_display_id = None
            exception_display_id = None
            if final_status_for_source == "Matched":
                summary['matched_count'] += 1
                action = "View"
                if best_target_idx != -1: target_used[best_target_idx] = True
                # 'final_reason' already holds the AI reason for the match
            elif final_status_for_source == "Partial Match":
                 summary['partial_match_count'] += 1
                 action = "Review"
                 if best_target_idx != -1: target_used[best_target_idx] = True
            else:  # Exception or Unmatched
                final_status_for_source = "Exception"; action = "Resolve"; summary['exceptions_count'] += 1
                exception_info = first_exception_found.get(i)
                if exception_info: final_reason, final_exception_type, best_target_tx = exception_info['reason'], exception_info['type'], exception_info['target_tx']
                target_internal_id = best_target_tx[INTERNAL_ID] if best_target_tx else None
                details_for_log = {  # Prepare details using internal names
                    "source_internal_id": source_internal_id,
                    "target_internal_id": target_internal_id,
                    "ai_reason": final_reason,
                    "exception_type": final_exception_type,
                    "title": f"{final_exception_type or 'Exc.'} for Src {source_internal_id}",
                    "description": source_internal_desc,
                    "amount": str(source_internal_amount),
                    "date": str(source_internal_date),
                    "transaction": {
                        "id": source_internal_id,
                        "date": str(source_internal_date),
                        "description": source_internal_desc,
                        "source": "Source",
                        "amount": str(source_internal_amount)
                    },
                    "discrepancy": {
                        "bank": {
                            "id": source_internal_id,
                            "date": str(source_internal_date),
                            "description": source_internal_desc,
                            "amount": str(source_internal_amount)
                        },
                        "erp": {
                            "id": target_internal_id,
                            "date": str(best_target_tx[INTERNAL_DATE]) if best_target_tx else 'N/A',
                            "description": best_target_tx[INTERNAL_DESC] if best_target_tx else '',
                            "amount": str(best_target_tx[INTERNAL_AMOUNT]) if best_target_tx else 'N/A'
                        } if best_target_tx else {}
                    }
                }
                exception_display_id = create_exception_log(job_id=job_id, exc_type=final_exception_type, priority=None, details_dict=details_for_log)
                if best_target_idx != -1 and not target_used[best_target_idx]: target_used[best_target_idx] = True

            # Create ReconciliationResultItem
            result_details = {
                "source_internal_id": source_tx[INTERNAL_ID],
                "target_internal_id": best_target_tx[INTERNAL_ID] if best_target_tx else None,
                "ai_reason": final_reason, # <-- Reason is included here
                "exception_type": final_exception_type,
                "source_desc": source_tx[INTERNAL_DESC],
                "target_desc": best_target_tx[INTERNAL_DESC] if best_target_tx else '',
                "exception_id_display": exception_display_id
            }
            display_id_for_item = f"SRC-{source_tx[INTERNAL_ID]}"

            result = ReconciliationResultItem(
                job_id=job_id, display_id=display_id_for_item,
                date=source_tx[INTERNAL_DATE], description=source_tx[INTERNAL_DESC][:200],
                amount=source_tx[INTERNAL_AMOUNT],
                status=final_status_for_source, action=action,
                # Ensure details are saved correctly
                details=json.loads(json.dumps(result_details, default=str))
            )
            results_to_add.append(result)
        # --- End Source Loop ---

        # --- Handle Unmatched Targets ---
        for j, target_tx in enumerate(target_transactions):
            if not target_used[j]:
                target_internal_id=target_tx[INTERNAL_ID]; target_internal_date=target_tx[INTERNAL_DATE]; target_internal_amount=target_tx[INTERNAL_AMOUNT]; target_internal_desc=target_tx[INTERNAL_DESC]
                status, exception_type, reason, action = "Exception", "Missing Transaction (Source)", "Target not matched.", "Resolve"; summary['exceptions_count'] += 1
                details_for_log = { "source_internal_id": None, "target_internal_id": target_internal_id, "ai_reason": reason, "exception_type": exception_type, "title": f"Missing Source for Tgt {target_internal_id}", "description": target_internal_desc, "amount": str(target_internal_amount), "date": str(target_internal_date), "transaction": { "id": target_internal_id, "date": str(target_internal_date), "description": target_internal_desc, "source": "Target", "amount": str(target_internal_amount) }, "discrepancy": { "bank": {}, "erp": { "id": target_internal_id, "date": str(target_internal_date), "description": target_internal_desc, "amount": str(target_internal_amount) } } }
                exception_display_id = create_exception_log( job_id=job_id, exc_type=exception_type, priority="Medium", details_dict=details_for_log )
                reason = "Process Conclusion: This target transaction did not match any available source transaction..."
                # ... create exception log ...
                details_for_log = {
                    # ...
                    "ai_reason": reason, # Store the process-derived reason
                    # ...
                }
                result = ReconciliationResultItem( job_id=job_id, display_id=f"TGT-{target_internal_id}", date=target_internal_date, description=target_internal_desc[:200], amount=target_internal_amount, status=status, action=action, details=json.loads(json.dumps(details_for_log, default=str)) )
                results_to_add.append(result)

        # --- Final Commit ---
        if results_to_add: db.session.add_all(results_to_add)
        # Commit results and any exceptions added via helper within the try block
        db.session.commit()
        logging.info(f"Saved results and exceptions for Job ID: {job_id}")

    except Exception as e: # General error handling for the whole process
        error_msg = str(e)
        logging.error(f"Critical error during reconciliation for Job ID {job_id}: {error_msg}", 
                     exc_info=True)
        db.session.rollback()  # Rollback any partial changes
        
        try:
            # Update summary with error info
            summary.update({
                'error': f"Processing error: {error_msg}",
                'matched_count': ReconciliationResultItem.query.filter_by(
                    job_id=job_id, status='Matched').count(),
                'partial_match_count': ReconciliationResultItem.query.filter_by(
                    job_id=job_id, status='Partial Match').count(),
                'exceptions_count': ExceptionLog.query.filter_by(
                    job_id=job_id).count()
            })
        except Exception as e_summary:
            logging.error(f"Error updating summary after failure for job {job_id}: {e_summary}")
            summary['error'] = f"Processing error: {error_msg}"
        
        raise ReconciliationError(f"Reconciliation failed: {error_msg}") from e

    logging.info(f"Finished reconciliation process for Job ID: {job_id}. Summary: {summary}")
    return {'summary': summary}
