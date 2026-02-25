from prometheus_client import Counter, Histogram

ingest_runs_total = Counter("afisha_ingest_runs_total", "Number of ingest runs", ["source", "status"])
api_request_latency = Histogram("afisha_api_request_latency_seconds", "API request latency", ["route"])
