import os

from sanic import Sanic
from app.auth import auth_bp
from app.views import views_bp
from config import Config
from sanic_jinja2 import SanicJinja2
from jinja2 import FileSystemLoader
from sanic_session import Session, InMemorySessionInterface
# from sanic_wtf import CSRFProtect

app = Sanic(__name__)

app.static('/static', './static')

# Initialize CSRF protection with the CSRF secret key
# csrf = CSRFProtect(app, secret=os.getenv("CSRF_SECRET_KEY"))

# Update configuration manually
app.config.update({key: getattr(Config, key) for key in dir(Config) if not key.startswith("__")})

# Initialize Jinja2 with a custom loader
jinja = SanicJinja2(app, loader=FileSystemLoader('app/templates'))

# Store the Jinja2 instance in the app context
app.ctx.jinja = jinja

# Setup session middleware
Session(app, interface=InMemorySessionInterface())  # Using in-memory session for simplicity

# Register blueprints
app.blueprint(auth_bp)
app.blueprint(views_bp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8778)
