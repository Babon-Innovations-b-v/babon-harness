# apps/assistant/core/tools/observability/

`prom_query` (`PROM_URL`) and `loki_query` (`LOKI_URL`, only registered when set).

- **An empty answer is not a health statement.** A metric name Prometheus does not know is a failure naming the closest real names.
- Every log line is labelled with the box and container it came from.
