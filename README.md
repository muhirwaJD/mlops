# K8s Log Analyzer — ML Engineer vs MLOps Demo

A FastAPI service that classifies Kubernetes log lines using zero-shot NLP. Built to demonstrate how **ML Engineers** and **MLOps Engineers** own separate layers of the same system.

---

## The Core Idea

| Role | Owns | How they change things |
|---|---|---|
| MLOps Engineer | `app/`, `Dockerfile`, `log-analyzer-helm/templates/`, `argocd/` | Code + infrastructure changes |
| ML Engineer | `log-analyzer-helm/values.yaml` → `candidateLabels` | Edit labels, push to Git — done |

When the ML Engineer updates `candidateLabels` in `values.yaml` and pushes to Git, ArgoCD detects the diff and rolls out a new pod automatically. **No image rebuild. No infrastructure code change.**

---

## How It Works

```
values.yaml (candidateLabels)
        ↓  Helm renders env var
CANDIDATE_LABELS = '["oom_kill","crashloop",...]'
        ↓  Pod restarts (checksum annotation triggers rollout)
lifespan() reads env var on startup
        ↓
POST /analyze  →  DistilBERT scores each label  →  returns top match
        ↓
/metrics  →  Prometheus scrapes inference latency + label counters
```

---

## Project Structure

```
mlops/
├── app/
│   ├── main.py              # FastAPI app — /analyze, /healthz, /metrics
│   ├── metrics.py           # Prometheus histogram + label counters
│   └── requirements.txt
├── log-analyzer-helm/       # Helm chart
│   ├── Chart.yaml
│   ├── values.yaml          # ← ML Engineer edits candidateLabels here
│   └── templates/
│       ├── _helpers.tpl
│       ├── deployment.yaml  # checksum annotation drives label rollouts
│       └── service.yaml
├── argocd/
│   └── application.yaml     # GitOps sync to OrbStack K8s cluster
├── Dockerfile
└── .python-version
```

---

## Quickstart — Local Development

```bash
# 1. Create and activate virtual environment
python -m venv mlops
source mlops/bin/activate

# 2. Install dependencies
pip install -r app/requirements.txt

# 3. Run the server
uvicorn app.main:app --reload

# 4. Test inference
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"log": "OOMKilled: container exceeded memory limit of 512Mi"}'

curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"log": "Back-off restarting failed container myapp in pod myapp-7d6f"}'

curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"log": "Failed to pull image myrepo/myapp:v2: 401 Unauthorized"}'

curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"log": "0/3 nodes available: 3 node(s) had taint node.kubernetes.io/not-ready"}'

curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"log": "The node was low on memory. Pod was evicted due to resource pressure"}'

# 5. Check metrics
open http://localhost:8000/metrics

# 6. Interactive API docs
open http://localhost:8000/docs
```

---

## Docker

```bash
# Build (model weights are baked in — no cold-start network calls in K8s)
docker build -t log-analyzer:latest .

# Run with custom labels
docker run -p 8000:8000 \
  -e CANDIDATE_LABELS='["oom_kill","crashloop","image_pull_error","node_not_ready","pod_eviction"]' \
  log-analyzer:latest
```

---

## Kubernetes (OrbStack + Helm + ArgoCD)

### Prerequisites
- [OrbStack](https://orbstack.dev) with Kubernetes enabled
- `helm` and `kubectl` installed
- ArgoCD installed in the cluster

### Install ArgoCD
```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

### Deploy via ArgoCD
```bash
# 1. Update repoURL in argocd/application.yaml to your GitHub repo
# 2. Apply the ArgoCD Application
kubectl apply -f argocd/application.yaml

# 3. Watch the pod come up
kubectl get pods -n log-analyzer -w
```

### Helm dry-run (verify rendered YAML before deploying)
```bash
helm template demo log-analyzer-helm/
```

---

## The Demo Flow

1. Send a POST request — observe the model classify a log line
2. Open `log-analyzer-helm/values.yaml` — show the `candidateLabels` list
3. Add a new label (e.g. `disk_pressure`) and push to Git
4. ArgoCD detects the diff and triggers a rolling update
5. Send a new request with a disk-related log — new label wins
6. Open `/metrics` — show `predicted_label_total` updating per label

**The point:** the ML Engineer just changed model behavior by editing a YAML file. The MLOps Engineer's code never changed.

---

## API Reference

### `POST /analyze`

Classifies a log line against a set of candidate labels.

**Request:**
```json
{
  "log": "Back-off restarting failed container myapp",
  "candidate_labels": ["crashloop", "oom_kill"]
}
```
`candidate_labels` is optional — omit it to use the labels from `values.yaml`.

**Response:**
```json
{
  "top_label": "crashloop",
  "scores": {
    "crashloop": 0.81,
    "oom_kill": 0.19
  },
  "device": "mps"
}
```

### `GET /healthz`
Returns `{"status": "ok", "model": "typeform/distilbert-base-uncased-mnli"}`.

### `GET /metrics`
Prometheus text format. Key metrics:
- `inference_latency_seconds` — histogram of model inference time
- `predicted_label_total{label="..."}` — counter per predicted label

---

## Model

**`typeform/distilbert-base-uncased-mnli`** — a DistilBERT model fine-tuned on NLI (Natural Language Inference). It uses zero-shot classification: no training on Kubernetes logs needed. You provide the candidate labels; the model scores how well each label fits the input text.

Device selection at startup: **MPS** (Apple Silicon M2/M3) → **CPU** fallback.
