from prometheus_client import Counter, Histogram, make_asgi_app

INFERENCE_LATENCY = Histogram(
    "inference_latency_seconds",
    "Time spent running zero-shot classification",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

PREDICTED_LABEL_COUNTER = Counter(
    "predicted_label_total",
    "Number of times each label was top-predicted",
    labelnames=["label"],
)

metrics_app = make_asgi_app()
