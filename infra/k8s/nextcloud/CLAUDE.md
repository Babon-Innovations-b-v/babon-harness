# infra/k8s/nextcloud/

Nextcloud (Service `nextcloud:80`) and its cron, two containers in one pod on claim `nextcloud-data` (subPath `nextcloud_data`). Settings, OIDC and session rules are in `infra/nextcloud/`.

- **The cron stays a container in this pod.** A second Deployment on the ReadWriteOnce claim is a second writer on another node.
- **`TRUSTED_PROXIES` is the private ranges** a cluster's pod network uses; without them Nextcloud logs Caddy's address for every user.
- The scripts in `infra/nextcloud/` run `occ` through compose; in the cluster run them with `kubectl -n nextcloud exec deploy/nextcloud -c nextcloud -- su -s /bin/sh www-data -c 'php occ ...'`.
