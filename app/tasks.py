from celery import Celery, group, chain
from config import CeleryConfig
from app.utils import extract_bookmarks_to_dataframe, reattach_bookmarks_from_dataframe, burst_pdf, merge_pdf, apply_ocr_on_pdf, session_scope, cleanup_tmp_dir
from app.models import File
from datetime import datetime
import os
import gc
import fitz  # PyMuPDF
import pandas as pd


celery = Celery('ocr_tasks')
celery.config_from_object(CeleryConfig)


@celery.task
def ocr_pdf_file(file_id, ocr_option="basic"):
    with session_scope() as session:
        file_entry = session.query(File).filter_by(id=file_id).first()
        if not file_entry:
            return
        
        # Step 1: Extract bookmarks before processing and convert DataFrame to list of dicts
        bookmarks_df = extract_bookmarks_to_dataframe(file_entry.file_path)
        bookmarks_list = bookmarks_df.to_dict(orient='records')  # Convert DataFrame to list of dicts for serialization

        # Step 2: Burst the PDF into batches
        batch_files = burst_pdf(file_entry.file_path)
        if not batch_files:
            return {"error": "Failed to burst the PDF", "file_path": file_entry.file_path}

        # Step 3: Run OCR on each batch asynchronously, passing the OCR option to each batch task
        ocr_tasks = group(
            ocr_pdf_page_batch.s(file_id, batch_file, start_page, end_page, ocr_option)
            for start_page, end_page, batch_file in batch_files
        )

        # Chain the OCR tasks with the merge_ocr_batches task, passing bookmarks as a list of dicts
        workflow = chain(
            ocr_tasks,
            merge_ocr_batches.s(file_id, bookmarks_list)
        )
        workflow.apply_async()


@celery.task
def ocr_pdf_page_batch(file_id, batch_file_path, start_page, end_page, ocr_option="basic"):
    try:
        if not os.path.exists(batch_file_path):
            raise FileNotFoundError(f"Batch file not found: {batch_file_path}")

        # Step 4: Apply OCR to the batch file, passing the selected OCR option
        ocr_file = apply_ocr_on_pdf(batch_file_path, ocr_option)
        return {
            "start_page": start_page,
            "end_page": end_page,
            "ocr_file": ocr_file
        }
    except Exception as e:
        return {"error": str(e), "batch_file_path": batch_file_path}



@celery.task
def merge_ocr_batches(results, file_id, bookmarks_list):
    with session_scope() as session:
        file_entry = session.query(File).filter_by(id=file_id).first()
        if not file_entry:
            return

        # Step 5: Verify results
        print(f"Raw results: {results}")
        if isinstance(results, dict):
            results = [results]

        # Verify if results is a list
        if not isinstance(results, list):
            print(f"Unexpected results format: {results}")
            return

        try:
            # Step 6: Sort the results by 'start_page'
            sorted_results = sorted(results, key=lambda x: x['start_page'])
            output_dir = os.path.dirname(file_entry.file_path)
            ocr_files = [res['ocr_file'] for res in sorted_results if 'ocr_file' in res]

            # Step 7: Merge the OCR'ed PDF files into one final PDF
            final_pdf_path = merge_pdf(ocr_files, output_dir, file_entry.file_name)

            # Step 8: Convert the list of dicts back to a DataFrame
            bookmarks_df = pd.DataFrame(bookmarks_list)
            
            # Step 9: Ensure final renaming happens correctly
            final_renamed_pdf_path = os.path.join(output_dir, f"{os.path.splitext(file_entry.file_name)[0]}_OCRed.pdf")
            if os.path.exists(final_pdf_path):
                os.rename(final_pdf_path, final_renamed_pdf_path)
                
            # Get number of pages in the final PDF
            pdf_document = fitz.open(final_renamed_pdf_path)
            total_pages = pdf_document.page_count
            pdf_document.close()
                
            # Step 10: Reattach the bookmarks to the final PDF
            reattach_bookmarks_from_dataframe(final_renamed_pdf_path, bookmarks_df, 1, total_pages)  #len(sorted_results))
                
            # Get the parent directory of the final PDF
            parent_dir = os.path.dirname(final_renamed_pdf_path)
            
            # Delete the file that ends with "_OCRed.pdf" and rename the one that ends with "_OCRed_with_bookmarks.pdf"
            # by replacing "_OCRed_with_bookmarks.pdf" with "_OCRed.pdf"
            
            # for file in os.listdir(parent_dir):
                # if file.endswith("_OCRed.pdf"):
                    # os.remove(os.path.join(parent_dir, file))
                # elif file.endswith("_OCRed_with_bookmarks.pdf"):
                    # os.rename(os.path.join(parent_dir, file), os.path.join(parent_dir, file.replace("_OCRed_with_bookmarks.pdf", "_OCRed.pdf")))
                    
            # The final_renamed_pdf_path should be the path to the renamed file
            # final_renamed_pdf_path = os.path.join(parent_dir, f"{os.path.splitext(file_entry.file_name)[0]}_OCRed.pdf")

            # Step 11: Update file entry status
            file_entry.output_path = final_renamed_pdf_path
            file_entry.status = 'Processed'
            file_entry.completed_at = datetime.utcnow()
            session.commit()

            # Cleanup temporary directory
            # tmp_dir = os.path.join(output_dir, 'tmp')
            # cleanup_tmp_dir(tmp_dir)

        except KeyError as e:
            print(f"Error merging PDFs: missing key {e}")
        except Exception as e:
            print(f"General error during merging: {e}")
            
        gc.collect()


@celery.task
def ocr_pdf_folder(folder_path, project_id):
    pass
