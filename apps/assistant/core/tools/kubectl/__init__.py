"""kubectl tool group, cluster inspection via the Python kubernetes client.

    k8s.py              load_config_once(): shared in-cluster vs kubeconfig bootstrap
    kubectl_get.py      pod/cronjob/deployment/service/node state (list view)
    kubectl_describe.py full single-resource detail (kubectl describe)
    kubectl_logs.py     pod log tail (traceback capture)
    kubectl_events.py   recent namespace events (OOMKilled, BackOff)
"""
