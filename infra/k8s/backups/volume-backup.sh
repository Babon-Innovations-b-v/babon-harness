#!/usr/bin/env bash
# Snapshot every PersistentVolumeClaim labelled harness/backup=true, in every
# namespace, as a CSI VolumeSnapshot in the claim's own namespace, then keep
# the newest BACKUP_KEEP ready snapshots of each claim and delete the rest.
#
# Runs in the volume-backup CronJob (./cronjob.yaml). Snapshots are
# crash-consistent: the volume is in use while it is taken.
#
# FAILURE POLICY: a claim whose snapshot is refused or never becomes ready is
# reported and the run goes on to the next claim; the run exits 1 if any claim
# failed, so the Job fails and kube_job_failed sees it. A claim's old
# snapshots are pruned only after its new one is ready, so a failing provider
# never deletes the last good copy.
set -uo pipefail

: "${BACKUP_KEEP:?}" "${BACKUP_SNAPSHOT_CLASS:?}"
stamp=$(date -u +%Y%m%d-%H%M)
failed=0
count=0

while read -r namespace claim; do
    [ -n "$claim" ] || continue
    count=$((count + 1))
    snapshot="$claim-$stamp"
    if ! kubectl -n "$namespace" apply -f - <<YAML
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: $snapshot
  labels:
    harness/backup-of: $claim
spec:
  volumeSnapshotClassName: $BACKUP_SNAPSHOT_CLASS
  source:
    persistentVolumeClaimName: $claim
YAML
    then
        echo "volume-backup: $namespace/$claim: snapshot refused" >&2
        failed=1
        continue
    fi
    if ! kubectl -n "$namespace" wait --for=jsonpath='{.status.readyToUse}'=true \
        "volumesnapshot/$snapshot" --timeout=30m; then
        echo "volume-backup: $namespace/$claim: $snapshot never became ready; old snapshots kept" >&2
        failed=1
        continue
    fi
    kubectl -n "$namespace" get volumesnapshot -l "harness/backup-of=$claim" \
        --sort-by=.metadata.creationTimestamp -o name \
        | head -n "-$BACKUP_KEEP" \
        | xargs -r kubectl -n "$namespace" delete \
        || { echo "volume-backup: $namespace/$claim: prune failed" >&2; failed=1; }
    echo "volume-backup: $namespace/$claim: $snapshot ready"
done < <(kubectl get pvc --all-namespaces -l harness/backup=true \
    -o jsonpath='{range .items[*]}{.metadata.namespace}{" "}{.metadata.name}{"\n"}{end}')

echo "volume-backup: $count claims, failed=$failed"
exit "$failed"
