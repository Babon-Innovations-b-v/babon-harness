# infra/k8s/backups/

CronJob `volume-backup`: every night at 01:30 (`ASSISTANT_TIMEZONE`) `volume-backup.sh` takes a CSI VolumeSnapshot of every claim labelled `harness/backup=true`, in the claim's namespace, labelled `harness/backup-of=<claim>`, and keeps the newest `BACKUP_KEEP` (default 7).

- **A claim that holds state carries the label; a cache does not.** That is the whole selection.
- **Old snapshots are pruned only after the new one is ready**, so a failing provider never deletes the last good copy. Do not move the prune ahead of the wait.
- `BACKUP_SNAPSHOT_CLASS` needs `deletionPolicy: Delete`, or a pruned snapshot keeps costing.
- Snapshots are crash-consistent. Restore: a new claim with `dataSource` naming the VolumeSnapshot, then point the workload at it.
- A failed run fails the Job; nothing pages on it until the monitoring piece watches namespace `backups`.
- First run by hand: `kubectl -n backups create job --from=cronjob/volume-backup first`.
