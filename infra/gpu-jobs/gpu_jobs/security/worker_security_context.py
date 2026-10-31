"""Hardened container SecurityContext shared by every notulen GPU pod.

One home so the Job and its placeholder cannot drift on the hardening
posture. The pod-level twin lives in ``worker_pod_security_context.py``.

FAILURE POLICY: pure object construction: nothing to swallow.
"""

from __future__ import annotations

from kubernetes import client


def worker_security_context() -> "client.V1SecurityContext":
    """Hardened SecurityContext for every GPU worker container.

    - allowPrivilegeEscalation=False: setuid binaries / no_new_privs.
    - capabilities.drop=[ALL]: the worker does not need CAP_NET_*, CAP_SYS_*,
      anything. If ffmpeg pops a shell on a crafted upload, dropping caps
      stops the shell from doing kernel-level damage.
    - privileged=False: explicit for defense in depth.
    - runAsNonRoot=True + runAsUser=1000: the kubelet refuses to start the
      pod if the image would run as uid 0.

    NOT set here:
    - readOnlyRootFilesystem: the model caches write under HOME at runtime;
      a read-only root would break the first model load.
    """
    return client.V1SecurityContext(
        allow_privilege_escalation=False,
        privileged=False,
        run_as_non_root=True,
        run_as_user=1000,
        capabilities=client.V1Capabilities(drop=["ALL"]),
    )
