import os
import time
from adobe.pdfservices.operation.auth.service_principal_credentials import ServicePrincipalCredentials
from adobe.pdfservices.operation.pdf_services import PDFServices
from adobe.pdfservices.operation.pdf_services_media_type import PDFServicesMediaType
from adobe.pdfservices.operation.pdfjobs.jobs.export_pdf_job import ExportPDFJob
from adobe.pdfservices.operation.pdfjobs.params.export_pdf.export_pdf_params import ExportPDFParams
from adobe.pdfservices.operation.pdfjobs.params.export_pdf.export_pdf_target_format import ExportPDFTargetFormat
from adobe.pdfservices.operation.pdfjobs.result.export_pdf_result import ExportPDFResult
import logging

class AdobePDFService:
    def __init__(self):
        self.credentials = ServicePrincipalCredentials(
            client_id=os.getenv('PDF_SERVICES_CLIENT_ID'),
            client_secret=os.getenv('PDF_SERVICES_CLIENT_SECRET')
        )
        self.pdf_services = PDFServices(credentials=self.credentials)

    def convert_chunk_to_docx(self, pdf_chunk_path):
        with open(pdf_chunk_path, 'rb') as file:
            input_stream = file.read()
        
        try:
            input_asset = self.pdf_services.upload(input_stream=input_stream, mime_type=PDFServicesMediaType.PDF)
            export_pdf_params = ExportPDFParams(target_format=ExportPDFTargetFormat.DOCX)
            export_pdf_job = ExportPDFJob(input_asset=input_asset, export_pdf_params=export_pdf_params)
            
            location = self.pdf_services.submit(export_pdf_job)
            pdf_services_response = self.pdf_services.get_job_result(location, ExportPDFResult)
            result_asset = pdf_services_response.get_result().get_asset()
            stream_asset = self.pdf_services.get_content(result_asset)

            output_path = f"{pdf_chunk_path.replace('.pdf', '.docx')}"
            with open(output_path, "wb") as docx_file:
                docx_file.write(stream_asset.get_input_stream())
            
            logging.info(f"Successfully converted chunk to DOCX: {output_path}")
            return output_path

        except Exception as e:
            logging.error(f"Failed to convert chunk: {pdf_chunk_path}. Error: {e}")
            time.sleep(60)
            return self.convert_chunk_to_docx(pdf_chunk_path)  # Retry on failure

