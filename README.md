# AgentRecon - Intelligent Reconciliation Solution

AgentRecon is an AI-powered reconciliation solution designed to automate and streamline the process of reconciling financial transactions between different systems. The application leverages artificial intelligence to match transactions, identify discrepancies, and suggest resolutions for exceptions.

## Table of Contents

- [Features](#features)
- [System Architecture](#system-architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [Backend Setup](#backend-setup)
  - [Frontend Setup](#frontend-setup)
  - [Database Setup](#database-setup)
  - [Redis Setup](#redis-setup)
  - [Celery Setup](#celery-setup)
  - [Azure OpenAI Setup](#azure-openai-setup)
- [Configuration](#configuration)
  - [Environment Variables](#environment-variables)
  - [Data Source Mappings](#data-source-mappings)
  - [Knowledge Base](#knowledge-base)
- [Running the Application](#running-the-application)
  - [Development Mode](#development-mode)
  - [Production Deployment](#production-deployment)
- [Usage Guide](#usage-guide)
  - [Starting a Reconciliation](#starting-a-reconciliation)
  - [Managing Exceptions](#managing-exceptions)
  - [Generating Reports](#generating-reports)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## Features

- **AI-Powered Matching**: Automatically match transactions between source and target systems
- **Intelligent Exception Handling**: Identify and categorize discrepancies with AI assistance
- **Customizable Data Mappings**: Configure mappings between different file formats and internal data structure
- **Interactive Dashboard**: Monitor reconciliation activities and key metrics
- **Exception Management**: Review and resolve exceptions with AI-suggested solutions
- **Reporting and Analytics**: Generate detailed reports on reconciliation activities

## System Architecture

AgentRecon follows a client-server architecture:

- **Frontend**: React-based single-page application
- **Backend**: Flask-based RESTful API server
- **Database**: SQL database (PostgreSQL for production, SQLite for development)
- **Task Queue**: Celery with Redis for background processing
- **AI Service**: Azure OpenAI integration for intelligent matching

## Prerequisites

- **Python 3.8+**
- **Node.js 14+** and npm
- **PostgreSQL** (for production) or SQLite (for development)
- **Redis** server
- **Azure OpenAI** API access (or alternative OpenAI provider)

## Installation

### Backend Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/your-organization/agentrec.git
   cd agentrec
   ```

2. Create and activate a Python virtual environment:
   ```bash
   # Windows
   python -m venv venv
   venv\Scripts\activate

   # macOS/Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install backend dependencies:
   ```bash
   cd agentrec-backend
   pip install -r requirements.txt
   ```

### Frontend Setup

1. Navigate to the frontend directory:
   ```bash
   cd agentrec-dashboard-react
   ```

2. Install frontend dependencies:
   ```bash
   npm install
   ```

### Database Setup

#### Development (SQLite)

SQLite is configured by default for development. No additional setup is required.

#### Production (PostgreSQL)

1. Install PostgreSQL if not already installed
2. Create a database for AgentRecon:
   ```bash
   createdb agentrec
   ```
3. Update the `DATABASE_URL` in your environment variables (see Configuration section)

### Redis Setup

1. Install Redis server:
   ```bash
   # Ubuntu/Debian
   sudo apt-get install redis-server

   # macOS
   brew install redis

   # Windows
   # Download and install from https://github.com/microsoftarchive/redis/releases
   ```

2. Start Redis server:
   ```bash
   # Linux/macOS
   redis-server

   # Windows
   # Start the Redis service or run redis-server.exe
   ```

### Celery Setup

Celery is used for background task processing, such as running reconciliation jobs asynchronously.

1. Ensure Celery is installed (it should be included in the requirements.txt):
   ```bash
   pip install celery[redis]
   ```

2. Create a `celery_worker.py` file in the `agentrec-backend` directory if it doesn't exist:
   ```python
   # celery_worker.py
   from agentrec-backend import create_app, celery

   app = create_app()
   app.app_context().push()
   ```

3. Create a `celery_app.py` file in the `agentrec-backend` directory if it doesn't exist:
   ```python
   # celery_app.py
   from celery import Celery

   celery = Celery(__name__)
   ```

4. Verify the Celery configuration in your `__init__.py` file:
   ```python
   # Import the celery instance from celery_app.py
   from .celery_app import celery

   def create_app(config_class=Config):
       app = Flask(__name__)
       # ...

       # Update the imported celery instance's config
       celery_config = {key[7:].lower(): val for key, val in app.config.items() if key.startswith('CELERY_')}
       celery.conf.update(celery_config)
       celery.conf.update(
           broker_url=app.config.get('CELERY_BROKER_URL'),
           result_backend=app.config.get('CELERY_RESULT_BACKEND')
       )

       # ...
   ```

### Azure OpenAI Setup

1. Create an Azure OpenAI resource in the Azure portal
2. Deploy models for:
   - Chat completion (e.g., gpt-35-turbo or gpt-4)
   - Embeddings (e.g., text-embedding-ada-002)
3. Note your endpoint, API key, API version, and deployment names for configuration

## Configuration

### Environment Variables

Create a `.env` file in the `agentrec-backend` directory with the following variables:

```
# Flask Configuration
SECRET_KEY=your-secret-key
FLASK_APP=.:create_app()
FLASK_DEBUG=1

# Database Configuration
# For SQLite (development)
# DATABASE_URL=sqlite:///instance/app.db

# For PostgreSQL (production)
DATABASE_URL=postgresql://username:password@localhost/agentrec

# Redis/Celery Configuration
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
CELERY_TASK_SERIALIZER=json
CELERY_RESULT_SERIALIZER=json
CELERY_ACCEPT_CONTENT=['json']
CELERY_TIMEZONE=UTC
CELERY_ENABLE_UTC=True

# Azure OpenAI Configuration
AZURE_OPENAI_ENDPOINT=https://your-resource-name.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_API_VERSION=2023-05-15
AZURE_OPENAI_CHAT_DEPLOYMENT_NAME=your-chat-deployment-name
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=your-embedding-deployment-name
```

### Data Source Mappings

Before using the application, you need to set up data source mappings to define how columns in your source and target files correspond to the internal data structure.

1. Start the application (see Running the Application section)
2. Access the admin interface or use the database directly to create mappings
3. For each mapping, define:
   - Mapping name (e.g., "Bank Statement Format")
   - Source type ("source" or "target")
   - Column mappings (JSON format mapping file headers to internal field names)
   - Date format string (if needed)

Example column mapping:
```json
{
  "Transaction ID": "internal_id",
  "Transaction Date": "internal_date",
  "Amount": "internal_amount",
  "Description": "internal_description",
  "Reference": "internal_reference"
}
```

### Knowledge Base

The knowledge base contains rules for transaction matching and exception identification. The default knowledge base is located at `agentrec-backend/static/knowledge_base.txt`.

You can customize the rules by editing this file. Each rule should follow the format:

```
Rule KB-XXX: Rule Name
DEFINITION: Description of the rule
CONDITION: Conditions for applying the rule
```

## Running the Application

### Development Mode

1. Start the Flask backend:
   ```bash
   # From the agentrec-backend directory with virtual environment activated
   flask run
   ```

2. Start Celery worker:
   ```bash
   # From the agentrec-backend directory with virtual environment activated
   celery -A celery_worker.celery worker --loglevel=info
   ```

   You can also start Celery with additional options:
   ```bash
   # Multiple workers with concurrency
   celery -A celery_worker.celery worker --loglevel=info --concurrency=4

   # Specify queue
   celery -A celery_worker.celery worker --loglevel=info -Q default
   ```

3. Start the React frontend:
   ```bash
   # From the agentrec-dashboard-react directory
   npm start
   ```

4. Access the application at http://localhost:3000

### Production Deployment

#### Backend Deployment

1. Set up a WSGI server (e.g., Gunicorn):
   ```bash
   pip install gunicorn
   ```

2. Start the application:
   ```bash
   gunicorn -w 4 "agentrec-backend:create_app()"
   ```

3. Set up Celery workers:
   ```bash
   celery -A celery_worker.celery worker --loglevel=info
   ```

   For production, consider using a process manager like Supervisor:
   ```bash
   # Install supervisor
   pip install supervisor

   # Create a configuration file (supervisor.conf)
   [program:celery]
   command=celery -A celery_worker.celery worker --loglevel=info
   directory=/path/to/agentrec-backend
   user=celery_user
   numprocs=1
   stdout_logfile=/var/log/celery/worker.log
   stderr_logfile=/var/log/celery/worker.log
   autostart=true
   autorestart=true
   startsecs=10
   stopwaitsecs=600

   # Start supervisor
   supervisord -c supervisor.conf
   ```

   You may also want to set up Celery Beat for scheduled tasks:
   ```bash
   celery -A celery_worker.celery beat --loglevel=info
   ```

4. Configure a web server (Nginx/Apache) to proxy requests to the WSGI server

#### Frontend Deployment

1. Build the React application:
   ```bash
   cd agentrec-dashboard-react
   npm run build
   ```

2. Deploy the contents of the `build` directory to your web server or CDN

## Usage Guide

### Starting a Reconciliation

1. Navigate to the Reconciliations page
2. Select the reconciliation type from the sidebar
3. Upload source and target files
4. Select appropriate data source mappings
5. Click "Run Reconciliation"
6. View the results once processing is complete

### Managing Exceptions

1. Navigate to the Exceptions page
2. Review the list of exceptions
3. Click on an exception to view details
4. Choose a resolution action:
   - Accept Match
   - Create Manual Match
   - Mark as Reconciled
   - Flag for Review
5. Add resolution notes
6. Click "Resolve Exception"

### Generating Reports

1. Navigate to the Reports page
2. Select the report type
3. Set parameters (date range, reconciliation types, etc.)
4. Click "Generate Report"
5. Export the report in your preferred format (Excel, CSV, PDF)

## Troubleshooting

### Common Issues

- **Database migration errors**: Run `flask db upgrade` to apply all migrations
- **Celery worker not processing tasks**:
  - Ensure Redis server is running
  - Check Celery worker logs for errors
  - Verify broker and result backend URLs in .env file
  - Make sure task modules are properly imported
- **Celery tasks stuck in PENDING state**:
  - Ensure Celery worker is running and consuming from the correct queue
  - Check for task routing issues
  - Verify that task serialization settings match between producer and consumer
- **AI service not working**: Check Azure OpenAI configuration in .env file
- **File upload issues**: Verify file format and size limits

### Celery Monitoring

You can monitor Celery tasks using Flower:

1. Install Flower:
   ```bash
   pip install flower
   ```

2. Start Flower:
   ```bash
   celery -A celery_worker.celery flower --port=5555
   ```

3. Access the Flower dashboard at http://localhost:5555

### Logs

- Backend logs: Check the console where Flask is running
- Celery logs: Check the console where Celery worker is running
  - For more detailed Celery logs: `celery -A celery_worker.celery worker --loglevel=debug`
- Frontend logs: Check the browser console

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Commit your changes: `git commit -m 'Add some feature'`
4. Push to the branch: `git push origin feature-name`
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

celery -A agentrec-backend.celery_app:celery worker --loglevel=info -P gevent -c 1