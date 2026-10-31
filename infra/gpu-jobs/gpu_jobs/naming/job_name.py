"""The Kubernetes Job-name grammar, part of the interface.

Callers that later need to find a Job (the dashboard matching live Jobs
against its queue, a person running ``kubectl get jobs``) must reproduce the
exact mangling the creators applied, so it lives in one place.

FAILURE POLICY: pure string mangling, nothing to swallow.
"""

from __future__ import annotations


def job_name(
    prefix: str, seed: str, *, seed_chars: int, suffix: str = ""
) -> str:
    """Mangle (prefix, seed) into the Job name the creators submit.

    Grammar: ``{prefix}-{seed[:seed_chars]}[-{suffix}]`` lowercased,
    trailing ``-`` stripped (K8s DNS-1123 names reject trailing dashes).
    ``seed_chars`` is keyword-only and has no default, because a silent
    default would change live Job names (notulen uses 20).

    ``suffix`` is appended AFTER the truncation, which is the whole point of
    it: a distinguisher folded into ``seed`` is cut off again whenever the
    seed is already longer than ``seed_chars``, and then every Job in the
    group asks for one name and all but the first come back 409.
    """
    name = f"{prefix}-{seed[:seed_chars]}".lower().rstrip("-")
    if suffix:
        name = f"{name}-{suffix.lower()}"
    return name
