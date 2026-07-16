#!/bin/sh
set -eu

admin_endpoint="${HYDRA_ADMIN_URL:?HYDRA_ADMIN_URL is required}"

ensure_client() {
    client_id="$1"
    client_secret="$2"
    scope="$3"
    audience="$4"

    if hydra get oauth2-client --endpoint "$admin_endpoint" "$client_id" >/dev/null 2>&1; then
        return
    fi

    hydra create oauth2-client \
        --endpoint "$admin_endpoint" \
        --id "$client_id" \
        --secret "$client_secret" \
        --grant-type client_credentials \
        --response-type token \
        --scope "$scope" \
        --audience "$audience"
}

ensure_client \
    "${AGENT_WORKFLOW_OAUTH_CLIENT_ID:?AGENT_WORKFLOW_OAUTH_CLIENT_ID is required}" \
    "${AGENT_WORKFLOW_OAUTH_CLIENT_SECRET:?AGENT_WORKFLOW_OAUTH_CLIENT_SECRET is required}" \
    "task.events.write" \
    "kardcraft.task-events"

ensure_client \
    "${TASK_ORCHESTRATOR_OAUTH_CLIENT_ID:?TASK_ORCHESTRATOR_OAUTH_CLIENT_ID is required}" \
    "${TASK_ORCHESTRATOR_OAUTH_CLIENT_SECRET:?TASK_ORCHESTRATOR_OAUTH_CLIENT_SECRET is required}" \
    "task.events.introspect" \
    "kardcraft.task-events"
