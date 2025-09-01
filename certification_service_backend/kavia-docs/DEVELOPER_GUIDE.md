# Developer Guide

## Introduction

### Background
This guide helps developers run the service locally, regenerate OpenAPI, and understand key flows to extend the implementation safely.

### Scope
Covers local setup, running the server, generating the OpenAPI spec, and understanding orchestration and audit touchpoints.

## Local Setup

### Requirements
- Python 3.11+
- PostgreSQL (or a compatible database reachable via DATABASE_URL)
- Env vars configured as per CONFIGURATION.md

### Install dependencies
Create and activate a virtual environment, then:
```
pip install -r certification_service_backend/requirements.txt
```

### Environment
Create a .env file in the repository root or export variables in your shell. See kavia-docs/CONFIGURATION.md for details.

Minimal example:
```
ENVIRONMENT=development
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/certification_db
AIRFLOW_BASE_URL=http://localhost:8080
WEBHOOK_SECRET=dev-shared-secret
```

## Running the Service

### Uvicorn
From the container root:
```
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

The scheduler starts on application startup and stops on shutdown. The database tables are created automatically for development via init_models.

## OpenAPI Specification

### Generate and write openapi.json
The project includes a helper script:
```
python -m src.api.generate_openapi
```
This imports the FastAPI app and writes the schema to:
- certification_service_backend/interfaces/openapi.json

Ensure the server code imports do not execute external calls at import time, as the generator imports the app module.

## Key Flows

### Certification Trigger Flow
- /certifications POST inserts a job and pending per-type results; triggers background orchestration.
- Orchestrator:
  - Triggers Airflow DAG per type based on AIRFLOW_DAG_MAP.
  - Marks results running, saves dag_run_id, and emits audit logs.
  - Background pollers finish each type with passed/failed, auditing terminalization.

### Reconciliation Loop
- The in-process scheduler scans for active jobs periodically, queries Airflow for dag_run_id states, and updates terminal states with audit entries.

### Webhooks
- GitLab (optional): Validates X-Gitlab-Token or X-Webhook-Secret; creates a code_quality job for push events.
- Airflow: Validates X-Webhook-Secret; updates result states for run_id (+optional type).

## Audit Integration Points

- User mutations (create, patch, mapping create, metadata upsert) include actor and request context.
- System transitions (orchestrator and scheduler) set actor to "orchestrator" or "scheduler".
- Webhook updates set actor to "airflow" when secret validation is enabled.

## Extending the System

### Adding a new certification type
- Add enum value to models/schemas.py CertificationType.
- Configure AIRFLOW_DAG_MAP to include a DAG id for the new type.
- No endpoint changes are needed if the new type is submitted in POST /certifications.

### Adding a repository provider
- Implement BaseRepoAdapter for the provider.
- Update get_repo_adapter to return the new adapter when selected.
- Ensure adapter resolves commits and provides project metadata as needed.

### Safety and Testing
- Do not persist secrets in audit logs.
- Keep OpenAPI in sync by regenerating after endpoint changes.
- Add unit/integration tests for new repository adapters and orchestration logic.

## Conclusion

### Summary
With environment-driven configuration, a clear orchestration pipeline, and comprehensive audit logging, the service is straightforward to run and extend. Use this guide to keep OpenAPI and documentation synchronized with code changes.
