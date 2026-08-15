FROM postgres:18-alpine

RUN apk add --no-cache aws-cli gnupg

COPY ops/backup/backup.sh /usr/local/bin/renouvelassur-backup
RUN chmod 0755 /usr/local/bin/renouvelassur-backup

ENTRYPOINT ["/usr/local/bin/renouvelassur-backup"]
