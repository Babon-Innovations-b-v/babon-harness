# infra/k8s/postgres/

Postgres 16 as a StatefulSet of one, Service `postgres.postgres.svc.cluster.local:5432`, claim `data-postgres-0` (subPath `postgres_data`). Nextcloud and notulen are its clients.

- **The init script is `infra/nextcloud/postgres-init.sh` itself**, read through `--load-restrictor LoadRestrictionsNone`. It runs only on an empty data directory.
- **Copy the compose volume only with both sides stopped and the same major version** (16). A newer image on old data refuses to start; that is a dump and restore, not a copy.
- The password is the only guard on 5432 inside the cluster, as on the compose network.
