#!/bin/sh
set -eu

ensure_stream() {
  name="$1"
  subjects="$2"
  retention="$3"
  max_age="$4"

  if nats --server "$NATS_URL" --user "$NATS_USER" --password "$NATS_PASSWORD" \
    stream info "$name" >/dev/null 2>&1; then
    nats --server "$NATS_URL" --user "$NATS_USER" --password "$NATS_PASSWORD" \
      stream edit "$name" --subjects "$subjects" \
      --max-age "$max_age" --force >/dev/null
  else
    nats --server "$NATS_URL" --user "$NATS_USER" --password "$NATS_PASSWORD" \
      stream add "$name" --subjects "$subjects" \
      --storage file --retention "$retention" --max-age "$max_age" \
      --replicas 1 --discard old --defaults >/dev/null
  fi
}

ensure_stream RUN_COMMANDS 'porfirium.run.command.*' workq 168h
ensure_stream RUN_EVENTS 'porfirium.run.event.*' limits 720h
ensure_stream CONVERSATION_EVENTS 'porfirium.conversation.event.*' interest 2160h
ensure_stream MESSAGE_DELTAS 'porfirium.message.delta.*' limits 15m
ensure_stream USER_INPUT 'porfirium.input.command.*' workq 720h
ensure_stream AUDIT_EVENTS 'porfirium.audit.event.*' limits 8760h
ensure_stream DEAD_LETTERS 'porfirium.dlq.*' limits 720h
