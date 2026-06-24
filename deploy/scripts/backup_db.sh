#!/usr/bin/env bash
#
# Dump the Supabase Postgres DB and upload a gzipped copy to Cloudflare R2
# (via its S3-compatible API).
# Used both by the weekly systemd timer and as the pre-migration safety dump
# in the deploy workflow. Any failure exits non-zero so the deploy can abort.
#
# Requires on the host: postgresql-client (pg_dump), awscli, gzip.
# Reads DATABASE_URL, BACKUP_S3_BUCKET, and S3_ENDPOINT_URL from the
# environment, sourcing ${PILLORA_ENV:-/opt/pillora/.env} when present so
# cron/manual runs work too.

set -euo pipefail

ENV_FILE="${PILLORA_ENV:-/opt/pillora/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

: "${DATABASE_URL:?DATABASE_URL must be set}"
: "${BACKUP_S3_BUCKET:?BACKUP_S3_BUCKET must be set}"
: "${S3_ENDPOINT_URL:?S3_ENDPOINT_URL must be set (Cloudflare R2 account endpoint)}"

# pg_dump speaks plain libpq URLs; strip the SQLAlchemy "+psycopg" driver suffix.
PG_URL="${DATABASE_URL/+psycopg/}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
key="db/pillora-${timestamp}.sql.gz"

echo "Dumping database -> s3://${BACKUP_S3_BUCKET}/${key} (R2)"

# Stream pg_dump -> gzip -> R2 without staging a local file.
# pipefail ensures a pg_dump failure fails the whole pipe.
pg_dump --no-owner --no-privileges "$PG_URL" \
  | gzip -9 \
  | aws s3 cp - "s3://${BACKUP_S3_BUCKET}/${key}" --endpoint-url "$S3_ENDPOINT_URL" --only-show-errors

echo "Backup complete: s3://${BACKUP_S3_BUCKET}/${key}"
