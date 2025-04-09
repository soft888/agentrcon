# config.py
import os
from dotenv import load_dotenv

load_dotenv() # Load variables from .env file

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'

    # --- Database ---
    # Use DATABASE_URL from .env for PostgreSQL
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'instance', 'app.db') # Fallback to SQLite if not set
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Celery ---
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL') or 'redis://localhost:6379/0'
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND') or 'redis://localhost:6379/0'

    # --- File Uploads / KB ---
    UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads')
    KNOWLEDGE_BASE_PATH = os.path.join(basedir, 'static', 'knowledge_base.txt')

    # --- Azure OpenAI ---
    AZURE_OPENAI_ENDPOINT = os.environ.get('AZURE_OPENAI_ENDPOINT')
    AZURE_OPENAI_API_KEY = os.environ.get('AZURE_OPENAI_API_KEY')
    AZURE_OPENAI_API_VERSION = os.environ.get('AZURE_OPENAI_API_VERSION')
    AZURE_OPENAI_CHAT_DEPLOYMENT_NAME = os.environ.get('AZURE_OPENAI_CHAT_DEPLOYMENT_NAME')
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME = os.environ.get('AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME')

    # Basic validation for Azure keys
    if not all([AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION, AZURE_OPENAI_CHAT_DEPLOYMENT_NAME, AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME]):
        print("Warning: One or more Azure OpenAI environment variables are missing.")


     # --- Ollama Config ---
    OLLAMA_BASE_URL = os.environ.get('OLLAMA_BASE_URL') or 'http://localhost:11434'
    OLLAMA_EMBEDDING_MODEL_NAME = os.environ.get('OLLAMA_EMBEDDING_MODEL_NAME') # e.g., 'nomic-embed-text'

    # --- Validation ---
    # Adjust validation if needed
    # if not all([... Azure Chat keys ...]): print("Warning: Azure OpenAI Chat variables missing.")
    if not all([OLLAMA_BASE_URL, OLLAMA_EMBEDDING_MODEL_NAME]):
        print("Warning: One or more Ollama environment variables are missing.")