"""Observability: Prometheus, Alertmanager, the alert relay and the deadmen.

Nothing is imported here on purpose: the relay container mounts this directory
and the systemd units run single modules from it, so each leaf must import on
its own.
"""
