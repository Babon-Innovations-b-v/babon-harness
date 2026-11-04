# infra/gpu-jobs

The `gpu_jobs` package: the only code that submits anything to the GPU cluster. One Job kind, the notulen transcription worker, plus the placeholder Pod that holds a GPU while a meeting records. The seam is `gpu_jobs/__init__.py`, whose docstring is the module map; callers use only its exports and import it lazily inside functions, so the dashboard boots without the `kubernetes` client. Bible: `infra/gpu`.

## Rules

- **Credentials by reference only.** Every secret reaches the pod through `secretKeyRef` on `notulen-worker-secrets`; settings through the `notulen-worker-config` ConfigMap. A value in the spec is readable by anyone who can read pods. `gpu_jobs/tests/test_a_notulen_job_waits_for_a_gpu_in_any_zone_without_a_deadline_and_its_pod_carries_no_credential_as_a_value.py` pins it.
- **The run cap sits on the pod, never the Job.** A Job-level `activeDeadlineSeconds` counts the wait for a GPU node and kills a meeting still Pending on a stock-out.
- **The placeholder stays a bare Pod at the `notulen-gpu-warmup` PriorityClass** (`infra/gpu/k8s/priorityclass.yaml`, value between -10 and -1). As a Job, every preemption is a failed Job and the dead-job watch pages on it.
- **Job and placeholder share `notulen_affinity` and `notulen_tolerations`**, or the placeholder warms a node the Job cannot use.
- **`naming/job_name.py` is interface.** The dashboard reproduces `job_name("notulen", job_id, seed_chars=20)` to match live Jobs; changing it breaks recovery.
- **`NOTULEN_WORKER_IMAGE` is required and pinned.** Never `:latest`: the Job pulls `IfNotPresent`.
- **`MAX_DAILY_JOBS` (default 50) is checked before any call**, counting `app=notulen-worker` Jobs in 24 h. A malformed value raises rather than disabling the ceiling.
- **Keep the BearerToken alias in `cluster/ensure_config.py`.** Without it every call goes out anonymous, gets 403, and the dashboard silently falls back to CPU.
- Settings read at call time: `GPU_NAMESPACE` (default `notulen`), `GPU_POOL` (comma list, preferred first, default `notulen-gpu`), `GPU_POOL_LABEL` (default `k8s.scaleway.com/pool-name`), `KUBECONFIG_B64`.
