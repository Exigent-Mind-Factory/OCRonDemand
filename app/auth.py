from sanic import Blueprint, response
from sqlalchemy.exc import IntegrityError
from app.models import User
from app.utils import session_scope, get_user_by_email

auth_bp = Blueprint('auth')

@auth_bp.route('/signup', methods=['POST'])
async def signup(request):
    fullname = request.json.get('fullname')
    email = request.json.get('email')
    password = request.json.get('password')

    if not email.endswith('@moraeglobal.com'):
        return response.json({'error': 'Email domain must be @moraeglobal.com'}, status=400)

    with session_scope() as session:
        user = User(fullname=fullname, email=email)
        user.set_password(password)

        try:
            session.add(user)
            session.commit()
        except IntegrityError:
            return response.json({'error': 'Email already registered'}, status=400)

    return response.json({'message': 'User registered successfully'})

@auth_bp.route('/login', methods=['POST'])
async def login(request):
    email = request.json.get('email')
    password = request.json.get('password')

    with session_scope() as session:
        user = get_user_by_email(session, email)

        if user is None or not user.check_password(password):
            return response.json({'error': 'Invalid credentials'}, status=401)

        # Reload the user into the session to ensure it is attached
        session.add(user)
        session.refresh(user)

        # Convert the user.id to a string when setting the cookie
        resp = response.json({'message': 'Logged in successfully'})
        resp.cookies.add_cookie(
            'user_id',
            str(user.id),
            httponly=True,
            max_age=3600,  # Set cookie for 1 hour
            secure=request.scheme == 'https'  # Only set Secure flag if using HTTPS
        )
        return resp
