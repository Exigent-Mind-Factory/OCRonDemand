import os
import subprocess
from contextlib import contextmanager
from PyPDF2 import PdfReader, PdfWriter
try:
    from PyPDF2 import PdfMerger
except ImportError:
    from PyPDF2 import PdfFileMerger as PdfMerger

from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from config import Config
import shutil
import logging
import fitz
import pandas as pd
import glob
import gc
from app.models import File
from datetime import datetime



# Import the User model from the models.py file
from app.models import User

# Setup logging to file
logging.basicConfig(level=logging.DEBUG, filename='burst_pdf_debug.log')

engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
Session = sessionmaker(bind=engine)

@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations."""
    session = Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def get_user_by_email(session, email):
    return session.query(User).filter_by(email=email).first()


class PDFManipulator:

    def __init__(self, input_pdf_path, outcome_pdf_path, file_id):
        self.input_pdf_path = input_pdf_path
        self.outcome_pdf_path = outcome_pdf_path
        self.file_id = file_id

    def remove_signature(self):
        # Removing signature from the PDF
        with open(self.input_pdf_path, 'rb') as file:
            reader = PdfReader(file)
            writer = PdfWriter()

            for page in range(len(reader.pages)):
                writer.add_page(reader.pages[page])

            with open(self.outcome_pdf_path, 'wb') as output_file:
                writer.write(output_file)
                
    def update_status(self, status):
        """Update the status of the file in the database"""
        with session_scope() as session:
            file_entry = session.query(File).filter_by(id=self.file_id).first()
            if file_entry:
                file_entry.status = status
                file_entry.completed_at = datetime.utcnow()
                session.commit()

    def apply_ocr(self, ocr_option="basic"):
        try:
            self.update_status('Processing')  # Set status to processing
            
            # Ensure that the signature is removed first
            self.remove_signature()

            if ocr_option.lower() == "basic":
                # Basic OCR using ocrmypdf
                cmd = [
                    'ocrmypdf',
                    '--optimize', '1',
                    '--force-ocr',
                    '--rotate-pages',
                    self.outcome_pdf_path,  # Input (unsigned PDF)
                    self.outcome_pdf_path  # Output (OCR applied)
                ]
                print(f"Running command: {' '.join(cmd)}")
                subprocess.run(cmd, check=True)

            elif ocr_option.lower() == "advanced":
                # Advanced OCR using Tesseract via ImageMagick and PyPDF2

                # Step 1: Convert PDF to images
                output_image_pattern = self.input_pdf_path.replace('.pdf', '_page_%d.png')
                cmd_convert = [
                    'magick',  
                    '-density', '300',  # High DPI for better OCR accuracy
                    self.input_pdf_path,
                    output_image_pattern
                ]
                print(f"Running ImageMagick command: {' '.join(cmd_convert)}")
                subprocess.run(cmd_convert, check=True)

                # Step 2: Apply OCR to images
                ocr_output_files = []
                for image_file in sorted(glob.glob(output_image_pattern.replace('%d', '*'))):
                    ocr_output_pdf = image_file.replace('.png', '.pdf')
                    cmd_ocr = [
                        'tesseract',
                        image_file,
                        ocr_output_pdf.replace('.pdf', ''),  # Output file name without extension
                        '--oem', '1',  # Use the LSTM OCR Engine
                        '--psm', '3',  # Page segmentation mode
                        'pdf'
                    ]
                    print(f"Running Tesseract OCR on: {image_file}")
                    subprocess.run(cmd_ocr, check=True)
                    ocr_output_files.append(ocr_output_pdf)

                # Step 3: Merge OCR'ed PDFs into a single output PDF
                if ocr_output_files:
                    self.merge_ocr_pdfs(ocr_output_files)

            else:
                raise ValueError("Invalid OCR option provided.")

            print(f"OCR applied successfully using {ocr_option}. Output saved to {self.outcome_pdf_path}")
            
            # Once all processing is done, update the file status
            self.update_status('Processed')  # Mark as processed

        except subprocess.CalledProcessError as e:
            print(f"Error executing command: {e.cmd}")
        except Exception as e:
            print(f"Error processing {self.input_pdf_path} with {ocr_option} OCR: {e}")
        finally:
            gc.collect()

    def merge_ocr_pdfs(self, ocr_pdf_files):
        try:
            merger = PdfMerger()
            for pdf_file in ocr_pdf_files:
                merger.append(pdf_file)

            with open(self.outcome_pdf_path, 'wb') as f_out:
                merger.write(f_out)
            print(f"Final OCR'ed PDF saved as: {self.outcome_pdf_path}")
        except Exception as e:
            print(f"Error merging OCR'ed PDFs: {e}")


def extract_bookmarks_to_dataframe(input_pdf):
    """
    Extract bookmarks from the input PDF and store them in a pandas DataFrame.
    """
    bookmarks = []
    pdf_document = fitz.open(input_pdf)

    # Get all the bookmarks (table of contents) from the PDF
    outlines = pdf_document.get_toc()

    # Extract each bookmark's level, title, and page number
    for outline in outlines:
        level, title, page_num = outline
        bookmarks.append({"bookmark": title, "line": level, "page": page_num - 1})  # Page is 0-indexed in PyMuPDF
        print(f"Extracted Bookmark: '{title}' on Page: {page_num}")

    # Convert the bookmarks list to a pandas DataFrame
    df_bookmarks = pd.DataFrame(bookmarks)
    pdf_document.close()
    print(df_bookmarks)
    return df_bookmarks


def reattach_bookmarks_from_dataframe(output_pdf, df_bookmarks, start_page, end_page):
    """
    Reattach bookmarks to the extracted pages using the pandas DataFrame.
    """
    pdf_document = fitz.open(output_pdf)
    toc = []  # This will hold the new Table of Contents (TOC) items

    # Iterate over the bookmarks and add them back if they are within the page range
    for _, row in df_bookmarks.iterrows():
        if start_page - 1 <= row['page'] < end_page:
            # Adjust the page number for the new document
            adjusted_page_num = row['page'] - (start_page - 1) + 1
            # Append the bookmark to the new TOC list
            toc.append([row['line'], row['bookmark'], adjusted_page_num])
            print(f"Reattached Bookmark: '{row['bookmark']}' on New Page: {adjusted_page_num}")

    # Set the TOC back to the new document
    pdf_document.set_toc(toc)
    
    # Create a new file to hold the updated PDF
    output_pdf = output_pdf.replace("_OCRed.pdf", "_OCRed_with_bookmarks.pdf")

    # Save the updated PDF without incremental saving (overwrite the original file)
    pdf_document.save(output_pdf, incremental=False)
    pdf_document.close()
    print(f"Final PDF with bookmarks saved to {output_pdf}")
    
    
def burst_pdf(file_path):
    logging.debug(f"Starting burst_pdf with file_path: {file_path}")
    try:
        pdf_reader = PdfReader(open(file_path, 'rb'))
        total_pages = len(pdf_reader.pages)
        logging.debug(f"Total pages in PDF: {total_pages}")
        
        batch_size = 10  # Number of pages per batch
        parent_dir = os.path.dirname(file_path)
        tmp_dir = os.path.join(parent_dir, 'tmp')
        
        # Attempt to create the tmp directory
        try:
            os.makedirs(tmp_dir, exist_ok=True)
            logging.debug(f"Created tmp directory at: {tmp_dir}")
        except Exception as e:
            logging.error(f"Failed to create tmp directory: {tmp_dir}. Error: {e}")
            return []

        burst_files = []
        for start_page in range(0, total_pages, batch_size):
            end_page = min(start_page + batch_size, total_pages)
            pdf_writer = PdfWriter()

            # Add pages to the writer
            for page in range(start_page, end_page):
                try:
                    pdf_writer.add_page(pdf_reader.pages[page])
                except Exception as e:
                    logging.error(f"Failed to add page {page} from {file_path}. Error: {e}")
                    continue

            batch_file_name = f"{os.path.splitext(os.path.basename(file_path))[0]}_pages_{start_page + 1}_to_{end_page}.pdf"
            batch_file_path = os.path.join(tmp_dir, batch_file_name)
            logging.debug(f"Creating batch file: {batch_file_path}")
            
            # Write the batch file
            try:
                with open(batch_file_path, 'wb') as batch_file:
                    pdf_writer.write(batch_file)
                burst_files.append((start_page + 1, end_page, batch_file_path))
                logging.debug(f"Successfully created batch file: {batch_file_path}")
            except Exception as e:
                logging.error(f"Failed to write batch file {batch_file_path}. Error: {e}")
                continue

        return burst_files

    except Exception as e:
        logging.error(f"Failed to burst PDF {file_path}. Error: {e}")
        return []


def merge_pdf(ocr_files, output_dir, original_file_name):
    final_pdf_name = f"{os.path.splitext(original_file_name)[0]}_OCRed.pdf"
    final_pdf_path = os.path.join(output_dir, final_pdf_name)
    pdf_writer = PdfWriter()

    for ocr_file in ocr_files:
        if os.path.exists(ocr_file):
            pdf_reader = PdfReader(open(ocr_file, 'rb'))
            for page in range(len(pdf_reader.pages)):
                pdf_writer.add_page(pdf_reader.pages[page])
        else:
            print(f"Warning: {ocr_file} does not exist and will not be included in the final document.")

    with open(final_pdf_path, 'wb') as output_file:
        pdf_writer.write(output_file)

    return final_pdf_path


def apply_ocr_on_pdf(file_path, file_id, ocr_option="basic"):
    output_path = file_path.replace("uploads", "ocr_output")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Create a PDFManipulator instance with the file_id argument
    manipulator = PDFManipulator(file_path, output_path, file_id)

    # Apply OCR based on the selected option
    manipulator.apply_ocr(ocr_option=ocr_option)

    return output_path


def cleanup_tmp_dir(tmp_dir):
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
