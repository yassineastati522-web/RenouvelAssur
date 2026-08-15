#!/bin/sh

set -eu

require_variable() {
    variable_name="$1"
    eval "variable_value=\${$variable_name:-}"
    if [ -z "$variable_value" ]; then
        echo "Configuration manquante: $variable_name" >&2
        exit 2
    fi
}

require_variable BACKUP_DATABASE_URL
require_variable BACKUP_ENCRYPTION_PASSPHRASE
require_variable S3_BUCKET_NAME
require_variable AWS_ACCESS_KEY_ID
require_variable AWS_SECRET_ACCESS_KEY
require_variable AWS_REGION

if [ "${#BACKUP_ENCRYPTION_PASSPHRASE}" -lt 32 ]; then
    echo "BACKUP_ENCRYPTION_PASSPHRASE doit contenir au moins 32 caractères." >&2
    exit 2
fi

case "$BACKUP_DATABASE_URL" in
    *sslmode=require*|*sslmode=verify-ca*|*sslmode=verify-full*) ;;
    *)
        echo "BACKUP_DATABASE_URL doit imposer SSL avec sslmode=require, verify-ca ou verify-full." >&2
        exit 2
        ;;
esac

BACKUP_PREFIX="${BACKUP_PREFIX:-renouvelassur}"
S3_SERVER_SIDE_ENCRYPTION="${S3_SERVER_SIDE_ENCRYPTION:-AES256}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
year="$(date -u +%Y)"
month="$(date -u +%m)"
day="$(date -u +%d)"
archive_name="renouvelassur-${timestamp}.dump.gpg"
temporary_directory="$(mktemp -d)"
dump_file="${temporary_directory}/renouvelassur-${timestamp}.dump"
encrypted_file="${temporary_directory}/${archive_name}"
checksum_file="${encrypted_file}.sha256"
object_prefix="${BACKUP_PREFIX%/}/${year}/${month}/${day}"

cleanup() {
    rm -rf -- "$temporary_directory"
}
trap cleanup EXIT HUP INT TERM
umask 077

aws_s3() {
    if [ -n "${S3_ENDPOINT_URL:-}" ]; then
        aws --endpoint-url "$S3_ENDPOINT_URL" s3 --region "$AWS_REGION" "$@"
    else
        aws s3 --region "$AWS_REGION" "$@"
    fi
}

upload_file() {
    local_file="$1"
    object_name="$2"
    if [ "$S3_SERVER_SIDE_ENCRYPTION" = "none" ]; then
        aws_s3 cp "$local_file" "s3://${S3_BUCKET_NAME}/${object_prefix}/${object_name}" --only-show-errors
    else
        aws_s3 cp "$local_file" "s3://${S3_BUCKET_NAME}/${object_prefix}/${object_name}" \
            --sse "$S3_SERVER_SIDE_ENCRYPTION" --only-show-errors
    fi
}

echo "Création de la sauvegarde PostgreSQL ${timestamp}."
pg_dump \
    --format=custom \
    --compress=9 \
    --no-owner \
    --no-privileges \
    --file "$dump_file" \
    "$BACKUP_DATABASE_URL"

if [ ! -s "$dump_file" ]; then
    echo "La sauvegarde produite est vide." >&2
    exit 1
fi
pg_restore --list "$dump_file" >/dev/null

printf '%s' "$BACKUP_ENCRYPTION_PASSPHRASE" | gpg \
    --batch \
    --yes \
    --pinentry-mode loopback \
    --passphrase-fd 0 \
    --symmetric \
    --cipher-algo AES256 \
    --output "$encrypted_file" \
    "$dump_file"

printf '%s' "$BACKUP_ENCRYPTION_PASSPHRASE" | gpg \
    --batch \
    --quiet \
    --pinentry-mode loopback \
    --passphrase-fd 0 \
    --decrypt "$encrypted_file" | pg_restore --list >/dev/null

(
    cd "$temporary_directory"
    sha256sum "$archive_name" > "${archive_name}.sha256"
)

echo "Envoi de l’archive chiffrée vers le stockage de sauvegarde."
upload_file "$encrypted_file" "$archive_name"
upload_file "$checksum_file" "${archive_name}.sha256"

echo "Sauvegarde vérifiée et transférée: ${object_prefix}/${archive_name}"
