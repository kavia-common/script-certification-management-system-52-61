# Audit Logging

## Introduction

### Background
Audit logging is implemented to provide traceability for all key operations and system events. The service records who did what, to which resource, and with which request context. This is essential for compliance, debugging, and operational insights.

### Scope
This document focuses on what is logged, how actor information is derived, and where the logs are persisted, strictly reflecting the current implementation.

## What Gets Logged

### API Mutations
- Creating certification jobs (/certifications POST)
- Patching certification jobs (/certifications/{run_id} PATCH)
- Creating mappings (/mappings POST)
- Upserting metadata (/metadata POST)

Each of these writes an audit log entry capturing the actor and the request context. The payload (or its essential fields) is included in the details to provide a snapshot of the change.

### Webhooks
- GitLab webhook triggers (webhooks/gitlab): action=webhook_create
- Airflow state updates (webhooks/airflow): action=webhook_update

Webhook audits include payload snapshots and flags indicating whether expected secrets were present in headers.

### Orchestration and Scheduler
- Orchestrator triggering and state transitions:
  - orchestrate_trigger
  - orchestrate_running
  - orchestrate_terminal
- Scheduler reconciliation updates:
  - scheduler_update

These indicate system-driven transitions with actor values like "orchestrator" and "scheduler".

## Data Model

Audit logs are persisted to the audit_logs table:

- id: bigint, autoincrement
- action: string (e.g., create, patch, upsert, webhook_create, webhook_update, orchestrate_trigger, orchestrate_running, orchestrate_terminal, scheduler_update)
- resource_type: string (e.g., certification_job, certification_result, mapping, metadata)
- resource_id: optional string corresponding to the affected entity (e.g., run_id or row id)
- actor: optional string representing the user or system component
- details: JSON payload capturing context (non-sensitive)
- created_at: timestamp

## Actor Extraction

### Header-based Extraction Order
- X-User-Id
- X-User
- X-Forwarded-User
- Authorization:
  - If "Bearer <token>", only the marker "bearer" is recorded (token is not persisted).
  - Otherwise only the scheme is retained (e.g., "basic").

This best-effort extraction is implemented by extract_actor_from_headers in src/core/audit.py and is used by endpoints that accept user mutation.

### System Actors
- "orchestrator": used by orchestration flows for triggers and status transitions.
- "scheduler": used by the background reconciliation loop.
- "airflow": used by Airflow webhook updates when the expected shared secret is configured and validated.

## Request Context Capture

build_request_context collects non-sensitive parts of the incoming request:

- method, path, query string, and client IP
- a strict subset of safe headers:
  - x-user-id
  - x-user
  - x-forwarded-user
  - x-request-id
  - x-gitlab-token
  - x-webhook-secret
- environment label from configuration

The context is stored in the details JSON of audit logs. Secret values should be treated carefully by downstream consumers.

## Example Entries

- Create certification job (user mutation):
  - action: "create"
  - resource_type: "certification_job"
  - resource_id: "<run_id>"
  - actor: "alice" (from X-User-Id)
  - details: includes provider, project_id, branch, payload snapshot, and request context.

- Orchestrator transition to running:
  - action: "orchestrate_running"
  - resource_type: "certification_result"
  - resource_id: "<result_id>"
  - actor: "orchestrator"
  - details: includes run_id and type.

- Airflow webhook update:
  - action: "webhook_update"
  - resource_type: "certification_job"
  - resource_id: "<run_id>"
  - actor: "airflow" (if secret configured)
  - details: includes payload snapshot and secrets_present indicator.

## Operational Considerations

- Log Volume: Orchestration and scheduler events can generate multiple audit rows per run. Ensure downstream processing and retention policies accommodate this.
- PII and Secrets: Only non-sensitive request context and header names are captured. Authorization secrets are not stored. Review any additions to headers to avoid accidental inclusion of secrets.
- Querying: Use timestamps and resource_id/resource_type fields to group events for a run or entity.

## Conclusion

### Summary
The service records all significant state changes and external interactions, preserving who performed them and the context in which they occurred, while taking care to avoid persisting secrets.
