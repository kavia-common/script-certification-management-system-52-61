# Certification Service Backend Configuration

## Introduction

### Background
This document explains how the service is configured via environment variables and the default values loaded by src/core/config.py.

### Scope
Only configuration that exists in the codebase is documented here.

## Settings

### Core app
- APP_NAME: Human-friendly application name. Default: "Certification Service Backend"
- ENVIRONMENT: Environment label (development/staging/production). Default: "development"
- DEBUG: Enable debug mode (true/false). Default: false
- HOST: Bind host. Default: 0.0.0.0
- PORT: Port. Default: 8000

### CORS
- CORS_ALLOW_ORIGINS: Comma-separated list or "*" (converted to list). Default: "*"
- CORS_ALLOW_CREDENTIALS: true/false. Default: true
- CORS_ALLOW_METHODS: Comma-separated list or "*" (string accepted). Default: "*"
- CORS_ALLOW_HEADERS: Comma-separated list or "*" (string accepted). Default: "*"
Security note: In non-development environments, "*" for CORS_ALLOW_ORIGINS is not allowed; if "*" is set, the service will restrict to an empty list (deny all)
until explicit origins are configured.

### Database
- DATABASE_URL: SQLAlchemy async URL, e.g., postgresql+asyncpg://user:password@host:port/db
  Default: postgresql+asyncpg://user:password@localhost:5432/certification_db

### Repository providers (GitLab)
- GITLAB_BASE_URL: Base API URL, e.g., https://gitlab.com
- GITLAB_TOKEN: Personal access token with read_api scope

### Airflow integration
- AIRFLOW_BASE_URL: Base URL to reach Airflow API
- AIRFLOW_USERNAME: Basic auth username (optional)
- AIRFLOW_PASSWORD: Basic auth password (optional)
- AIRFLOW_TIMEOUT: HTTP timeout in seconds (float). Default: 15.0
- AIRFLOW_DAG_MAP: JSON object mapping certification types to DAG IDs. If not set, defaults are:
  {
    "unit": "cert_unit_tests",
    "extended_unit": "cert_extended_unit_tests",
    "e2e": "cert_e2e_tests",
    "soak": "cert_soak_tests",
    "performance": "cert_performance_tests",
    "code_quality": "cert_code_quality",
    "network_security": "cert_network_security",
    "manual_compliance": "cert_manual_compliance"
  }

### Webhooks security
- WEBHOOK_SECRET: Shared secret for generic webhooks (header: X-Webhook-Secret)
- GITLAB_WEBHOOK_SECRET: GitLab specific shared secret (header: X-Gitlab-Token)
- WEBHOOK_HMAC_SECRET: Secret used to validate HMAC signatures for webhook requests. Client must send:
  - X-Signature: hex-encoded HMAC of the raw request body
  - X-Signature-Algo: sha256 (default) or sha1
If both header-based shared secrets are unset, the service accepts webhook requests in development mode. When WEBHOOK_HMAC_SECRET is set, signature validation is enforced.

### Orchestration and scheduler
- ORCH_POLL_INTERVAL: Seconds between polling Airflow run status. Default: 10.0
- ORCH_MAX_POLL_SECONDS: Max seconds to poll before timeout. Default: 7200.0
- ORCH_RETRY_ATTEMPTS: Retry attempts for transient errors when triggering DAGs. Default: 3
- ORCH_RETRY_BACKOFF: Exponential backoff base. Default: 1.5

### Authentication
- AUTH_BEARER_TOKENS: Comma-separated list of accepted bearer tokens. Required in non-development environments for mutating endpoints (POST/PATCH).
  - In development, if unset, mutating endpoints are allowed without bearer token for local testing.

### Optional site URL
- SITE_URL: Public site URL for future integrations

## Notes

### CORS parsing
CORS_ALLOW_ORIGINS accepts a single string or comma-separated list; it is normalized to a list.

### DAG map override
If AIRFLOW_DAG_MAP is provided, it must be valid JSON. If parsing fails, defaults are used.

### Development defaults
If webhook secrets are not set, webhook endpoints accept requests to simplify local testing.

## Conclusion

### Summary
Configuration is environment-driven using Pydantic Settings. Airflow, GitLab, orchestration tuning, and webhook security can be adjusted without code changes.
