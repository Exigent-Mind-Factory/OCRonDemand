from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import uuid as uuid_lib
from sqlalchemy.dialects.postgresql import UUID

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    fullname = Column(String(100), nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    projects = relationship('Project', back_populates='user')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Client(Base):
    __tablename__ = 'clients'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    projects = relationship('Project', back_populates='client')

class Project(Base):
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    client = relationship('Client', back_populates='projects')
    user = relationship('User', back_populates='projects')
    files = relationship('File', back_populates='project')

    
class File(Base):
    __tablename__ = 'files'
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False)
    file_metadata = Column(Text, nullable=True)
    output_path = Column(String(255), nullable=True)
    file_path = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default='Not processed')
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    uuid = Column(UUID(as_uuid=True), default=uuid_lib.uuid4, unique=True, nullable=False)
    project = relationship('Project', back_populates='files')    
    

# class Document(Base):
    # __tablename__ = 'documents'
    # id = Column(Integer, primary_key=True)
    # project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    # file_name = Column(String(255), nullable=False)
    # file_path = Column(String(255), nullable=False)
    # output_path = Column(String(255), nullable=True)
    # status = Column(String(50), nullable=False, default='Pending')
    # created_at = Column(DateTime, default=datetime.datetime.utcnow)
    # completed_at = Column(DateTime, nullable=True)
    # project = relationship('Project', back_populates='documents')

# Establish the back_populates relationship
User.projects = relationship('Project', order_by=Project.id, back_populates='user')
Client.projects = relationship('Project', order_by=Project.id, back_populates='client')
Project.files = relationship('File', order_by=File.id, back_populates='project')
# Project.documents = relationship('Document', order_by=Document.id, back_populates='project')
