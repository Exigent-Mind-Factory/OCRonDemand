from sanic import Blueprint, response
from sanic.exceptions import Forbidden
from werkzeug.utils import secure_filename
import os
import uuid
from app.models import File, Project, Client, User  # Assuming User model exists
from app.utils import session_scope
from app.tasks import ocr_pdf_page_batch, merge_ocr_batches, ocr_pdf_file
from PyPDF2 import PdfReader
from celery import group
from celery.result import GroupResult
import shutil
import aiofiles
# from sanic.response import stream

views_bp = Blueprint('views')

def get_user_from_request(request):
    user_id = request.cookies.get('user_id')
    if user_id:
        with session_scope() as session:
            user = session.query(User).filter_by(id=user_id).first()
            return user
    return None

@views_bp.route('/', methods=['GET'])
async def home(request):
    user = get_user_from_request(request)
    return request.app.ctx.jinja.render('home.html', request, user=user)

@views_bp.route('/signup', methods=['GET'])
async def show_signup_form(request):
    user = get_user_from_request(request)
    return request.app.ctx.jinja.render('signup.html', request, user=user)

@views_bp.route('/login', methods=['GET'])
async def show_login_form(request):
    user = get_user_from_request(request)
    return request.app.ctx.jinja.render('login.html', request, user=user)

@views_bp.route('/create_project', methods=['POST'])
async def create_project(request):
    user_id = request.cookies.get('user_id')
    if not user_id:
        return response.json({'error': 'You must be logged in to create a project'}, status=403)

    client_name = request.json.get('client_name')
    project_name = request.json.get('project_name')

    if not client_name or not project_name:
        return response.json({'error': 'Client name and project name are required'}, status=400)

    with session_scope() as session:
        client = session.query(Client).filter_by(name=client_name).first()
        if not client:
            client = Client(name=client_name)
            session.add(client)
            session.commit()

        project = Project(name=project_name, client=client, user_id=user_id)
        session.add(project)
        session.commit()

        return response.json({'message': 'Project created successfully', 'project_id': project.id, 'client_id': client.id})

@views_bp.route('/my_projects', methods=['GET'])
async def my_projects(request):
    user_id = request.cookies.get('user_id')
    if not user_id:
        return response.redirect('/login')
    
    with session_scope() as session:
        projects = session.query(Project).filter_by(user_id=user_id).all()
        project_list = []
        for project in projects:
            files = [
                {
                    "id": file.id,
                    "name": file.file_name,
                    "status": file.status,
                    "download_url": f"/download/{file.id}" if file.status == "Processed" else None,
                    "error_url": f"/error/{file.id}" if file.status == "Failed" else None,
                    "created_at": file.created_at.strftime('%Y-%m-%d %H:%M:%S')  # Convert to string
                }
                for file in project.files
            ]
            project_list.append({
                "name": project.name,
                "client_name": project.client.name,  # Get the client name
                "files": files
            })
        
        return response.json(project_list)

@views_bp.route('/ocr/<project_id>', methods=['GET'])
async def show_ocr_page(request, project_id):
    user = get_user_from_request(request)
    user_id = request.cookies.get('user_id')
    if not user_id:
        return response.redirect('/login')

    with session_scope() as session:
        project = session.query(Project).filter_by(id=project_id).first()
        if not project:
            return response.redirect('/')

    return request.app.ctx.jinja.render('ocr.html', request, project_id=project_id, user=user)

@views_bp.route('/upload_single_pdf', methods=['POST'])
async def upload_single_pdf(request):
    user_id = request.cookies.get('user_id')
    project_id = request.form.get('project_id')
    if not user_id or not project_id:
        raise Forbidden("You need to log in and select a project to upload files")

    # Check if this is a chunked upload
    chunk = request.files.get('chunk')
    chunk_index = int(request.form.get('chunk_index', 0))
    total_chunks = int(request.form.get('total_chunks', 1))
    filename = secure_filename(request.form.get('file_name'))

    if not filename.lower().endswith('.pdf'):
        return response.json({'error': 'Invalid file type. Only PDFs are allowed.'}, status=400)

    # Generate a unique UUID for this upload
    unique_id = str(uuid.uuid4())

    # Create a unique directory for the file chunks using UUID
    directory = os.path.join('uploads', str(user_id), str(project_id), unique_id)
    os.makedirs(directory, exist_ok=True)

    # Save the current chunk
    chunk_path = os.path.join(directory, f"{filename}.part{chunk_index}")
    with open(chunk_path, 'wb') as f:
        f.write(chunk.body)

    # If the last chunk is received, merge all chunks
    if chunk_index == total_chunks - 1:
        final_file_path = os.path.join(directory, filename)
        with open(final_file_path, 'wb') as final_file:
            for i in range(total_chunks):
                part_path = os.path.join(directory, f"{filename}.part{i}")
                with open(part_path, 'rb') as part_file:
                    final_file.write(part_file.read())
                os.remove(part_path)  # Clean up the chunk part file

        with session_scope() as session:
            project = session.query(Project).filter_by(id=project_id).first()
            if not project:
                return response.json({'error': 'Project not found'}, status=404)

            file_entry = File(
                project_id=project_id,
                file_name=filename,
                file_size=os.path.getsize(final_file_path),
                file_path=final_file_path,
                status='Not processed'
            )
            session.add(file_entry)
            session.commit()
            file_id = file_entry.id  # Access the id while the session is still open

        return response.json({'message': 'File uploaded and merged successfully', 'file_id': file_id})

    return response.json({'message': f'Chunk {chunk_index + 1}/{total_chunks} uploaded successfully'})


@views_bp.route('/upload_single_pdf_chunked', methods=['POST'])
async def upload_single_pdf_chunked(request):
    user_id = request.cookies.get('user_id')
    project_id = request.form.get('project_id')
    client_id = request.form.get('client_id')
    if not user_id or not project_id:
        raise Forbidden("You need to log in and select a project to upload files")

    chunk_index = int(request.form.get('chunk_index'))
    total_chunks = int(request.form.get('total_chunks'))
    file_name = secure_filename(request.form.get('file_name'))
    chunk = request.files.get('chunk')

    # Generate a unique UUID for this upload
    

    # Save chunk to a temporary file
    temp_dir = os.path.join('uploads', str(user_id), str(client_id), str(project_id))   
    os.makedirs(temp_dir, exist_ok=True)
    
    chunk_temp_dir = os.path.join('uploads', str(user_id), str(client_id), str(project_id), 'temp')
    os.makedirs(chunk_temp_dir, exist_ok=True)
    
    temp_file_path = os.path.join(chunk_temp_dir, f'{file_name}.part{chunk_index}')
    with open(temp_file_path, 'wb') as f:
        f.write(chunk.body)

    # Combine chunks if all have been uploaded
    if chunk_index + 1 == total_chunks:
        final_file_path = os.path.join('uploads', str(user_id), str(client_id), str(project_id), file_name)
        os.makedirs(os.path.dirname(final_file_path), exist_ok=True)
        with open(final_file_path, 'wb') as final_file:
            for i in range(total_chunks):
                part_file_path = os.path.join(chunk_temp_dir, f'{file_name}.part{i}')
                with open(part_file_path, 'rb') as part_file:
                    final_file.write(part_file.read())
                os.remove(part_file_path)  # Remove part after merging
            os.rmdir(chunk_temp_dir)  # Remove temp directory after merging
            
        # Generate a unique UUID folder and move this file into it.
        unique_id = str(uuid.uuid4())
        unique_dir = os.path.join(os.path.dirname(final_file_path), str(uuid.uuid4()) )
        os.makedirs(unique_dir, exist_ok=True)
        shutil.move(final_file_path, unique_dir)
        
        # Get the final unique file path
        final_file_path = os.path.join(unique_dir, file_name)

        # Add the file to the database within a session
        with session_scope() as session:
            project = session.query(Project).filter_by(id=project_id).first()
            if not project:
                return response.json({'error': 'Project not found'}, status=404)

            file_entry = File(
                uuid=unique_id,
                project_id=project_id,
                file_name=file_name,
                file_size=os.path.getsize(final_file_path),
                file_path=final_file_path,
                status='Not processed'
            )
            session.add(file_entry)
            session.commit()

            # Access the file ID before closing the session
            file_id = file_entry.id

        return response.json({'message': 'File uploaded successfully', 'file_id': file_id})

    return response.json({'message': 'Chunk uploaded successfully'})



@views_bp.route('/start_ocr/<file_id>', methods=['POST'])
async def start_ocr(request, file_id):
    with session_scope() as session:
        file_entry = session.query(File).filter_by(id=file_id).first()
        if not file_entry:
            return response.json({'error': 'File not found'}, status=404)

        file_entry.status = 'Processing'
        session.commit()

        # Start the OCR process by calling ocr_pdf_file
        ocr_pdf_file.delay(file_id)

    return response.json({'message': 'OCR processing started successfully'})


@views_bp.route('/upload_bulk_pdf', methods=['POST'])
async def upload_bulk_pdf(request):
    user_id = request.cookies.get('user_id')
    project_id = request.form.get('project_id')
    if not user_id or not project_id:
        raise Forbidden("You need to log in and select a project to upload files")

    if 'files' not in request.files:
        return response.json({'error': 'No file part'}, status=400)

    files = request.files.getlist('files')

    with session_scope() as session:
        project = session.query(Project).filter_by(id=project_id).first()
        if not project:
            return response.json({'error': 'Project not found'}, status=404)

        for upload_file in files:
            filename = secure_filename(upload_file.name)
            file_size = len(upload_file.body)

            if not filename.lower().endswith('.pdf'):
                return response.json({'error': 'Invalid file type. Only PDFs are allowed.'}, status=400)

            # Create a unique directory for each file using UUID
            directory = os.path.join('uploads', str(user_id), str(project_id), str(uuid.uuid4()))
            os.makedirs(directory, exist_ok=True)

            file_path = os.path.join(directory, filename)
            with open(file_path, 'wb') as f:
                f.write(upload_file.body)

            file_entry = File(
                project_id=project_id,
                file_name=filename,
                file_size=file_size,
                file_path=file_path,
                status='Not processed'
            )
            session.add(file_entry)

        session.commit()

    return response.json({'message': 'Files uploaded successfully'})


@views_bp.route('/download/<file_id:int>', methods=['GET'])
async def download_file(request, file_id):
    with session_scope() as session:
        file_entry = session.query(File).filter_by(id=file_id).first()
        if not file_entry:
            return response.json({'error': 'File not found'}, status=404)

        # Construct the OCR'ed filename
        original_filename = file_entry.file_name
        base_name, ext = os.path.splitext(original_filename)
        ocr_filename = f"{base_name}_OCRed{ext}"
        file_path = os.path.join(os.path.dirname(file_entry.file_path), ocr_filename)

        if not os.path.exists(file_path):
            return response.json({'error': 'OCRed file not found on server'}, status=404)

        # Serve the file for download
        headers = {
            'Content-Disposition': f'attachment; filename="{ocr_filename}"'
        }

        return await response.file(file_path, filename=ocr_filename, mime_type='application/pdf', headers=headers)


# @views_bp.route('/download/<file_id:int>', methods=['GET'])
# async def download_file(request, file_id):
    # with session_scope() as session:
        # file_entry = session.query(File).filter_by(id=file_id).first()
        # if not file_entry:
            # return response.json({'error': 'File not found'}, status=404)

        # Construct the OCR'ed filename
        # original_filename = file_entry.file_name
        # base_name, ext = os.path.splitext(original_filename)
        # ocr_filename = f"{base_name}_OCRed{ext}"
        # file_path = os.path.join(os.path.dirname(file_entry.file_path), ocr_filename)

        # if not os.path.exists(file_path):
            # return response.json({'error': 'OCRed file not found on server'}, status=404)

        # Serve the file for download in chunks
        # headers = {
            # 'Content-Disposition': f'attachment; filename="{ocr_filename}"',
            # 'Content-Type': 'application/pdf',
        # }

        # async def file_stream(response):
            # async with aiofiles.open(file_path, 'rb') as f:
                # chunk = await f.read(8192)  # Read in 8KB chunks
                # while chunk:
                    # await response.write(chunk)
                    # chunk = await f.read(8192)

        # return stream(file_stream, headers=headers)



@views_bp.route('/logout', methods=['POST'])
async def logout(request):
    resp = response.redirect('/login')
    resp.cookies.delete_cookie('user_id')
    return resp
