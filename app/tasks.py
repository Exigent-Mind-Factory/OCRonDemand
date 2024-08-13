from celery import Celery, group, chain
from config import CeleryConfig
from app.utils import burst_pdf, merge_pdf, apply_ocr_on_pdf, session_scope, cleanup_tmp_dir
from app.models import File
from datetime import datetime
import os
import gc

celery = Celery('ocr_tasks')
celery.config_from_object(CeleryConfig)


@celery.task
def ocr_pdf_file(file_id):
    with session_scope() as session:
        file_entry = session.query(File).filter_by(id=file_id).first()
        if not file_entry:
            return
        
        # Burst the PDF into batches
        batch_files = burst_pdf(file_entry.file_path)
        if not batch_files:
            return {"error": "Failed to burst the PDF", "file_path": file_entry.file_path}

        # Run OCR on each batch asynchronously
        ocr_tasks = group(
            ocr_pdf_page_batch.s(file_id, batch_file, start_page, end_page)
            for start_page, end_page, batch_file in batch_files
        )

        # Chain the OCR tasks with the merge_ocr_batches task
        workflow = chain(
            ocr_tasks,
            merge_ocr_batches.s(file_id)
        )
        workflow.apply_async()


@celery.task
def ocr_pdf_page_batch(file_id, batch_file_path, start_page, end_page):
    try:
        if not os.path.exists(batch_file_path):
            raise FileNotFoundError(f"Batch file not found: {batch_file_path}")

        ocr_file = apply_ocr_on_pdf(batch_file_path)
        return {
            "start_page": start_page,
            "end_page": end_page,
            "ocr_file": ocr_file
        }
    except Exception as e:
        return {"error": str(e), "batch_file_path": batch_file_path}


@celery.task
def merge_ocr_batches(results, file_id):
    with session_scope() as session:
        file_entry = session.query(File).filter_by(id=file_id).first()
        if not file_entry:
            return

        # Check the structure of results
        print(f"Raw results: {results}")

        if isinstance(results, dict):
            results = [results]

        # Verify if results is a list
        if not isinstance(results, list):
            print(f"Unexpected results format: {results}")
            return

        # Sort the results by 'start_page' to ensure the correct order
        try:
            sorted_results = sorted(results, key=lambda x: x['start_page'])
            output_dir = os.path.dirname(file_entry.file_path)
            ocr_files = [res['ocr_file'] for res in sorted_results if 'ocr_file' in res]
            final_pdf = merge_pdf(ocr_files, output_dir, file_entry.file_name)

            # Update file entry status
            file_entry.output_path = final_pdf
            file_entry.status = 'Processed'
            file_entry.completed_at = datetime.utcnow()
            session.commit()

            # Cleanup temporary directory
            tmp_dir = os.path.join(output_dir, 'tmp')
            cleanup_tmp_dir(tmp_dir)

        except KeyError as e:
            print(f"Error merging PDFs: missing key {e}")
        except Exception as e:
            print(f"General error during merging: {e}")
            
        gc.collect()



@celery.task
def ocr_pdf_folder(folder_path, project_id):
    pass
