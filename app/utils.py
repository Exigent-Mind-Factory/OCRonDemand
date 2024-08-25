import os
import subprocess
from contextlib import contextmanager
from PyPDF2 import PdfReader, PdfWriter
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from config import Config
import shutil
import logging
import fitz
import pandas as pd


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

    def __init__(self, input_pdf_path, outcome_pdf_path):
        self.input_pdf_path = input_pdf_path
        self.outcome_pdf_path = outcome_pdf_path

    def remove_signature(self):
        with open(self.input_pdf_path, 'rb') as file:
            reader = PdfReader(file)
            writer = PdfWriter()

            for page in range(len(reader.pages)):
                writer.add_page(reader.pages[page])

            with open(self.outcome_pdf_path, 'wb') as output_file:
                writer.write(output_file)
                
                
    def apply_ocr(self):
        try:
            # Ensure that the signature is removed first
            self.remove_signature()

            # Prepare the ocrmypdf command
            cmd = [
                'ocrmypdf',
                '--optimize', '1',
                '--force-ocr',
                '--rotate-pages',
                self.outcome_pdf_path,  # Input (unsigned PDF)
                self.outcome_pdf_path  # Output (OCR applied)
            ]

            # Run the ocrmypdf command
            subprocess.run(cmd, check=True)
        except Exception as e:
            print(f"Error processing {self.input_pdf_path}: {e}")
            
            
    def apply_ocr_with_tesseract(self):
        try:
            # Pre-process the image (convert to TIFF for better results)
            tiff_output = self.input_pdf_path.replace('.pdf', '.tiff')

            # Convert PDF to high-quality TIFF using ImageMagick (requires ImageMagick installed)
            cmd_convert = [
                'magick',  # Use 'magick' for ImageMagick 7+
                '-density', '300',  # DPI
                '-depth', '8',  # Bit-depth
                '-background', 'white',
                self.input_pdf_path,
                tiff_output
            ]
            print(f"Running command: {' '.join(cmd_convert)}")
            subprocess.run(cmd_convert, check=True)

            # Run Tesseract directly on the TIFF image
            cmd_ocr = [
                'tesseract',
                tiff_output,
                self.outcome_pdf_path.replace('.pdf', ''),  # Output file name without extension
                '--oem', '1',  # Use the LSTM OCR Engine
                '--psm', '3',  # Page segmentation mode
                'pdf'
            ]
            print(f"Running command: {' '.join(cmd_ocr)}")
            subprocess.run(cmd_ocr, check=True)

            print(f"OCR applied successfully using Tesseract. Output saved to {self.outcome_pdf_path}")

            # Clean up TIFF file
            if os.path.exists(tiff_output):
                os.remove(tiff_output)
            


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

def apply_ocr_on_pdf(file_path):
    output_path = file_path.replace("uploads", "ocr_output")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    manipulator = PDFManipulator(file_path, output_path)
    manipulator.apply_ocr()
    return output_path

def cleanup_tmp_dir(tmp_dir):
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
