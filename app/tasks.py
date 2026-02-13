from celery import Celery, group, chain, chord
from config import CeleryConfig
from app.utils import extract_bookmarks_to_dataframe, reattach_bookmarks_from_dataframe, burst_pdf, merge_pdf, apply_ocr_on_pdf, session_scope, cleanup_tmp_dir
from app.models import File
from datetime import datetime
import os
import gc
import fitz 
import pandas as pd
from docx import Document

from app.utils import split_pdf, merge_docx_files, cleanup_temp_files, process_in_batches

import time
import logging

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

        # Step 3: Create a group of OCR tasks
        ocr_tasks = [
            ocr_pdf_page_batch.s(file_id, batch_file, start_page, end_page, ocr_option)
            for start_page, end_page, batch_file in batch_files
        ]

        # Step 4: Use a chord to wait for all OCR tasks to finish before triggering merge_ocr_batches
        callback = merge_ocr_batches.s(file_id, bookmarks_list)
        
        workflow = chord(ocr_tasks)(callback)
        return workflow
 

@celery.task
def ocr_pdf_page_batch(file_id, batch_file_path, start_page, end_page, ocr_option="basic"):
    try:
        if not os.path.exists(batch_file_path):
            raise FileNotFoundError(f"Batch file not found: {batch_file_path}")

        # Step 4: Apply OCR to the batch file, passing the selected OCR option
        ocr_file = apply_ocr_on_pdf(batch_file_path, file_id, ocr_option)
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
            # Check for any failed batches
            errors = [res for res in results if 'error' in res]
            if errors:
                print(f"Some batches failed: {errors}")
                file_entry.status = 'Failed'
                session.commit()
                return {"error": "Some batches failed", "details": errors}

            # Step 6: Sort the results by 'start_page'
            sorted_results = sorted(results, key=lambda x: x['start_page'])
            output_dir = os.path.dirname(file_entry.file_path)
            ocr_files = [res['ocr_file'] for res in sorted_results if 'ocr_file' in res]

            if not ocr_files:
                print("No OCR files to merge")
                file_entry.status = 'Failed'
                session.commit()
                return {"error": "No OCR files to merge"}

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
            reattach_bookmarks_from_dataframe(final_renamed_pdf_path, bookmarks_df, 1, total_pages)

            # Step 11: Update file entry status to OCR Completed
            file_entry.output_path = final_renamed_pdf_path
            file_entry.status = 'OCR Completed'
            file_entry.completed_at = datetime.utcnow()
            session.commit()

            # Cleanup temporary directory
            tmp_dir = os.path.join(output_dir, 'tmp')
            cleanup_tmp_dir(tmp_dir)

            # Trigger DOCX conversion after OCR completion
            process_pdf_to_docx.delay(final_renamed_pdf_path, file_id)

        except KeyError as e:
            print(f"Error merging PDFs: missing key {e}")
            file_entry.status = 'Failed'
            session.commit()
        except Exception as e:
            print(f"General error during merging: {e}")
            file_entry.status = 'Failed'
            session.commit()
            
        gc.collect()


@celery.task
def ocr_pdf_folder(folder_path, project_id):
    pass



MAX_REQUESTS_PER_BATCH = 20
BATCH_COOLDOWN = 30  # Cooldown period in seconds


@celery.task
def process_pdf_to_docx(file_path, file_id):
    """Converts an OCR’ed PDF to DOCX and updates the database record."""

    # Start DOCX conversion and set status to 'Processing'
    with session_scope() as session:
        file_entry = session.query(File).filter_by(id=file_id).first()
        if not file_entry:
            return
        file_entry.conversion_status = 'Processing'
        session.commit()

    try:
        # Step 1: Split the PDF into chunks for batch processing

        # Instead of taking the OCR'ed document, take the original PDF before OCR.
        file_path = file_path.split("_OCRed")[0] + ".pdf"

        chunk_paths = split_pdf(file_path, pages_per_chunk=20)

        # Step 2: Convert each chunk to DOCX and process in batches
        docx_paths = process_in_batches(chunk_paths)

        # Step 3: Merge all DOCX chunks into a single DOCX file
        output_dir = os.path.dirname(file_path)
        output_file_path = os.path.join(output_dir, f"{os.path.splitext(os.path.basename(file_path))[0]}_OCRed.docx")
        merge_docx_files(docx_paths, output_file_path)

        # Update the database with the conversion status and DOCX path
        with session_scope() as session:
            file_entry = session.query(File).filter_by(id=file_id).first()
            if file_entry:
                file_entry.docx_path = output_file_path
                file_entry.conversion_status = 'Completed'  # Set to Completed after successful DOCX conversion
                session.commit()


        # Trigger RAW DOCX creation once DOCX conversion completes
        generate_raw_docx.delay(file_id)

        return output_file_path

    except Exception as e:
        # Update conversion status to 'Failed' in case of an error
        print(f"The conversion of the OCR'ed PDF to DOCX failed!")
        logging.info(f"The conversion of the OCR'ed PDF to DOCX failed: {e}")

        with session_scope() as session:
            file_entry = session.query(File).filter_by(id=file_id).first()
            if file_entry:
                file_entry.conversion_status = 'Failed'
                session.commit()
        raise e




@celery.task
def generate_raw_docx(file_id):
    """Generate a raw DOCX with no formatting from the converted DOCX."""
    with session_scope() as session:
        file_entry = session.query(File).filter_by(id=file_id).first()
        if not file_entry or not file_entry.docx_path:
            return None  # If no converted DOCX exists, exit

        # Define path for the raw DOCX
        output_dir = os.path.dirname(file_entry.docx_path)
        raw_docx_path = os.path.join(output_dir, f"{os.path.splitext(file_entry.file_name)[0]}_RAW.docx")

        # Load the converted DOCX
        original_doc = Document(file_entry.docx_path)
        raw_doc = Document()  # Create a new blank DOCX

        # Extract text without any formatting and add it to the new document
        # for para in original_doc.paragraphs:
            # raw_doc.add_paragraph(para.text)

        # for para in original_doc.paragraphs:
            # if para.text.strip():  # Check if the paragraph has non-blank text
                # raw_doc.add_paragraph(para.text)

        for para in original_doc.paragraphs:
            if para.text.strip():  # Check if the paragraph has non-blank text
                # Add a plain paragraph without any styling
                new_para = raw_doc.add_paragraph(para.text)

                # Remove any potential numbering or indentation by resetting paragraph formatting
                new_para.paragraph_format.left_indent = None
                new_para.paragraph_format.right_indent = None
                new_para.paragraph_format.first_line_indent = None
                new_para.paragraph_format.space_before = None
                new_para.paragraph_format.space_after = None
                new_para.paragraph_format.alignment = None
        
                # Ensure no text is bolded or italicized
                for run in new_para.runs:
                    run.bold = False
                    run.italic = False
                    run.underline = False

        # Save the raw DOCX
        raw_doc.save(raw_docx_path)

        # Update file entry with raw_docx path
        file_entry.raw_docx_path = raw_docx_path  # You might need to add this column in your model
        session.commit()

    return raw_docx_path

