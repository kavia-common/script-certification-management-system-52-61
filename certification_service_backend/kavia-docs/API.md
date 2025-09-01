# Certification Service Backend API

## Introduction

### Background
This document describes the REST API exposed by the certification_service_backend FastAPI application. It enables clients to create and manage certification jobs, configure branch-to-environment mappings, manage metadata, and receive or send webhook events for orchestration.

### Scope
The documentation reflects the current implementation in the repository. It includes endpoint contracts, request and response models, security considerations, and audit logging behavior.

## Endpoints

### Health

#### Health Check
- Method: GET
- Path: /
- Summary: Health Check
- Response: 200 OK with {"message":"Healthy"}

#### Health with DB status
- Method: GET
- Path: /health
- Summary: Health with DB status
- Response: 200 OK with HealthResponse:
  - message: string
  - db_connected: boolean

### Certifications

#### Create a certification job
- Method: POST
- Path: /certifications
- Summary: Create a certification job
- Headers (optional for actor extraction): X-User-Id, X-User, X-Forwarded-User, Authorization
- Request body: TriggerCertificationRequest
- Responses:
  - 201 Created -> CertificationRunResponse
  - 400 Invalid request

Behavior:
- Persists a CertificationJob and per-type CertificationResult rows.
- Attempts to enrich metadata with repository info using provider adapters (e.g., GitLab).
- Writes an audit log entry with action=create, resource_type=certification_job, resource_id=run_id, actor from headers, and request context.
- Triggers orchestration in the background to launch Airflow DAGs per certification type.

#### Get certification job by run_id
- Method: GET
- Path: /certifications/{run_id}
- Summary: Get certification job by run_id
- Responses:
  - 200 OK -> CertificationRunResponse
  - 404 Not found

#### Patch certification job
- Method: PATCH
- Path: /certifications/{run_id}
- Summary: Patch certification job
- Headers (optional for actor extraction): X-User-Id, X-User, X-Forwarded-User, Authorization
- Request body: PatchCertificationRequest
- Responses:
  - 200 OK -> CertificationRunResponse
  - 404 Not found

Behavior:
- Updates mutable fields (status, environment, metadata).
- Writes an audit log entry with action=patch and request context.

### Mappings

#### List branch-environment mappings
- Method: GET
- Path: /mappings
- Query params: provider (optional), project_id (optional)
- Response: 200 OK -> List[MappingResponse]

#### Create a branch-environment mapping
- Method: POST
- Path: /mappings
- Headers (optional for actor extraction): X-User-Id, X-User, X-Forwarded-User, Authorization
- Request body: MappingItem
- Response: 201 Created -> MappingResponse

Behavior:
- Writes an audit log entry with action=create, resource_type=mapping.

### Metadata

#### List metadata
- Method: GET
- Path: /metadata
- Query params: key, provider, project_id, branch (all optional)
- Response: 200 OK -> List[MetadataItemResponse]

#### Upsert metadata item
- Method: POST
- Path: /metadata
- Headers (optional for actor extraction): X-User-Id, X-User, X-Forwarded-User, Authorization
- Request body: MetadataUpsert
- Response: 201 Created -> MetadataItemResponse

Behavior:
- Upserts by composite scope (provider, project_id, branch, key).
- Writes an audit log entry with action=upsert, resource_type=metadata.

### Webhooks

#### GitLab webhook (optional trigger)
- Method: POST
- Path: /webhooks/gitlab
- Headers (security): X-Gitlab-Token or X-Webhook-Secret if configured
- Request body: GitLabWebhookPush
- Responses:
  - 200 OK -> WebhookAck (accepted/ignored)
  - 401 Unauthorized (if secret mismatch)

Behavior:
- When object_kind=push, triggers a conservative default certification job for the branch in ref using type=code_quality.
- Writes an audit log entry with action=webhook_create and payload snapshot.

#### Airflow state webhook
- Method: POST
- Path: /webhooks/airflow
- Headers (security): X-Webhook-Secret (if configured)
- Request body: AirflowTaskEvent
- Responses:
  - 200 OK -> WebhookAck
  - 400 Invalid payload (unknown run_id)
  - 401 Unauthorized (secret mismatch)

Behavior:
- Updates per-type CertificationResult based on Airflow state and recomputes the aggregate CertificationJob status.
- Writes an audit log entry with action=webhook_update and details.

## Models

### Enums
- CertificationType: code_quality | network_security | manual_compliance | unit | extended_unit | e2e | soak | performance
- CertificationStatus: pending | running | passed | failed | cancelled

### Requests
- RepositoryRef: { provider, project_id, branch, commit_sha? }
- TriggerCertificationRequest: { repo, types[], environment?, metadata{}, notify_webhook? }
- PatchCertificationRequest: { status?, environment?, metadata? }
- MappingItem: { provider, project_id, branch_pattern, environment, is_active? }
- MetadataUpsert: { key, value{}, provider?, project_id?, branch? }
- GitLabWebhookPush: subset of GitLab push event fields
- AirflowTaskEvent: { run_id, type?, state, task_id?, dag_id?, dag_run_id?, logs_url? }

### Responses
- CertificationRunResponse: { run_id, status, created_at, types[], environment? }
- MappingResponse: mapping fields with timestamps
- MetadataItemResponse: metadata fields with timestamps
- HealthResponse: { message, db_connected }
- WebhookAck: { accepted, message }

## Audit Logging

### What is captured
- Action type (create, patch, upsert, webhook_create, webhook_update, orchestrate_trigger, orchestrate_running, orchestrate_terminal, scheduler_update)
- Resource type and id
- Actor: extracted from headers or system components (e.g., orchestrator, scheduler, airflow when secret validated)
- Details: payload snapshots and request context (method, path, limited safe headers, environment)

### Actor extraction
- Order: X-User-Id -> X-User -> X-Forwarded-User -> Authorization (records only the scheme, e.g., "bearer")
- Implemented by src/core/audit.py extract_actor_from_headers and build_request_context

## Security

### Webhook secrets
- GitLab: X-Gitlab-Token (GITLAB_WEBHOOK_SECRET)
- Generic: X-Webhook-Secret (WEBHOOK_SECRET)
- If not set, development mode accepts requests for easier testing.

### CORS
- Configurable via environment; defaults allow all for development.

## OpenAPI

An up-to-date OpenAPI schema is checked in at:
- certification_service_backend/interfaces/openapi.json

Regenerate using:
- python -m src.api.generate_openapi (ensures app import and writes to interfaces/openapi.json)

## Logging and Correlation

The backend emits structured JSON logs. Common fields include:
- request_id: Set per HTTP request (from X-Request-Id if provided, otherwise generated).
- run_id: Set when a certification run is created or processed (orchestrator, scheduler, webhooks).
- actor: Derived from headers for user operations, or system components ("orchestrator", "scheduler", "airflow").
- component: api | orchestrator | scheduler | webhook.
- event: Machine-friendly event name (e.g., http_request, cert_job_created, dag_triggered).

Client guidance:
- Provide X-Request-Id in API requests to correlate access logs and endpoint handling.
- Use the run_id returned by POST /certifications to filter orchestration, scheduler, and webhook logs for that run.

## Examples

### Create certification
Request:
```
POST /certifications
Headers: X-User-Id: alice
Body:
{
  "repo": {"provider":"gitlab","project_id":"123","branch":"feature-x"},
  "types": ["code_quality","unit"],
  "environment": "dev",
  "metadata": {"ticket":"ABC-123"}
}
```
Response:
```
201
{
  "run_id": "abcd1234ef567890",
  "status": "pending",
  "created_at": "2025-01-01T12:34:56Z",
  "types": ["code_quality","unit"],
  "environment": "dev"
}
```

### Airflow webhook update
```
POST /webhooks/airflow
Header: X-Webhook-Secret: <shared>
Body: { "run_id":"abcd1234ef567890", "type":"unit", "state":"success" }
```

## Conclusion

### Summary
The API allows clients to trigger and manage certification runs, configure mapping and metadata, and integrate with external systems via secure webhooks. Every mutating operation is audit logged with actor and request context captured for traceability.
