#!/bin/bash
cd /home/kavia/workspace/code-generation/script-certification-management-system-52-61/certification_service_backend
source venv/bin/activate
flake8 .
LINT_EXIT_CODE=$?
if [ $LINT_EXIT_CODE -ne 0 ]; then
  exit 1
fi

