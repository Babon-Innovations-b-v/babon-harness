# infra/k8s/deploy/

The deploy loop's namespace, its PriorityClass `deploy-loop` and the vault Secret. The loop's own workloads arrive in a later piece.

- **`deploy-loop` has `preemptionPolicy: Never`.** Its pods are scheduled first and evicted last, but never evict anything to get a place: they share the system pool with the apps. Do not switch it to preempt.
- Every deploy loop pod (the cycle, the gate's test runs, the image builder, the push receiver) sets `priorityClassName: deploy-loop`. A gate pod pushed off its node is a run that could not finish, and that ships nothing.
- The gate's test runs select the `gate` pool role and tolerate its taint (`infra/cluster/CLAUDE.md`).
