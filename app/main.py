import json
import os
import time
from contextlib import asynccontextmanager
from typing import Optional

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import pipeline

from app.metrics import INFERENCE_LATENCY, PREDICTED_LABEL_COUNTER, metrics_app

MODEL_NAME = "typeform/distilbert-base-uncased-mnli"

classifier = None
default_labels: list[str] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    global classifier, default_labels

    device_id = "mps" if torch.backends.mps.is_available() else "cpu"
    classifier = pipeline("zero-shot-classification", model=MODEL_NAME, device=device_id)

    raw = os.getenv("CANDIDATE_LABELS", "")
    default_labels = json.loads(raw) if raw else [
        "oom_kill", "crashloop", "image_pull_error", "node_not_ready", "pod_eviction",
    ]
    yield
    classifier = None


app = FastAPI(title="K8s Log Analyzer", version="1.0.0", lifespan=lifespan)
app.mount("/metrics", metrics_app)


class AnalyzeRequest(BaseModel):
    log: str
    candidate_labels: Optional[list[str]] = None


class AnalyzeResponse(BaseModel):
    top_label: str
    scores: dict[str, float]
    device: str


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    if classifier is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    labels = request.candidate_labels or default_labels
    if not labels:
        raise HTTPException(status_code=422, detail="No candidate_labels provided")

    start = time.perf_counter()
    result = classifier(request.log, candidate_labels=labels)
    elapsed = time.perf_counter() - start

    INFERENCE_LATENCY.observe(elapsed)
    top_label = result["labels"][0]
    PREDICTED_LABEL_COUNTER.labels(label=top_label).inc()

    return AnalyzeResponse(
        top_label=top_label,
        scores=dict(zip(result["labels"], result["scores"])),
        device="mps" if torch.backends.mps.is_available() else "cpu",
    )


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_NAME}
