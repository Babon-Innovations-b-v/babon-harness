#!/bin/bash
# Create Nextcloud's own database and user inside the shared postgres.
#
# The postgres image runs every script in /docker-entrypoint-initdb.d/
# ONCE, on the first boot of an empty data volume (compose.yml mounts
# this file there). The stack's database, POSTGRES_DB, is created by the
# image itself; this script adds a second database and user so Nextcloud
# has separate credentials and cannot read the stack's tables.
#
# Runs INSIDE the postgres container, where compose sets NEXTCLOUD_DB_*.
# Wipe the postgres volume and it runs again on the next start.
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --set=nc_user="$NEXTCLOUD_DB_USER" \
    --set=nc_pass="$NEXTCLOUD_DB_PASSWORD" \
    --set=nc_db="$NEXTCLOUD_DB_NAME" <<-'EOSQL'
	CREATE USER :"nc_user" WITH PASSWORD :'nc_pass';
	CREATE DATABASE :"nc_db" OWNER :"nc_user";
	REVOKE ALL ON DATABASE :"nc_db" FROM PUBLIC;
EOSQL

echo "created nextcloud database '$NEXTCLOUD_DB_NAME' owned by '$NEXTCLOUD_DB_USER'"
