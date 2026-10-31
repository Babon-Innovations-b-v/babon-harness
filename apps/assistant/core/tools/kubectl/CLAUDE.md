# apps/assistant/core/tools/kubectl/

Read-only Kubernetes tools. Registered only when `cluster_configured()` finds a kubeconfig at `KUBECONFIG` or an in-cluster account. The default namespace is `ASSISTANT_NAMESPACE`.

- Give the kubeconfig a read-only role; the tools pin read verbs as a second lock.
