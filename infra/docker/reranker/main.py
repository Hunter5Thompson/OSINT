"""TEI-compatible reranker service using transformers + GPU."""

import os
import logging
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

MODEL_ID = os.getenv("MODEL_ID", "BAAI/bge-reranker-v2-m3")
HF_TOKEN = os.getenv("HF_TOKEN", None) or None
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
MAX_LENGTH = int(os.getenv("MAX_LENGTH", "512"))

tokenizer = None
model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global tokenizer, model
    logger.info("Loading reranker model %s on %s", MODEL_ID, DEVICE)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, token=HF_TOKEN)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_ID,
        token=HF_TOKEN,
        torch_dtype=torch.float16 if DEVICE == "cuda" else torch.float32,
    ).to(DEVICE)
    model.eval()
    logger.info("Reranker ready on %s", DEVICE)
    yield
    logger.info("Shutting down reranker")


app = FastAPI(lifespan=lifespan)


class RerankRequest(BaseModel):
    query: str
    texts: list[str]
    truncate: bool = True
    raw_scores: bool = False


class RerankResult(BaseModel):
    index: int
    score: float


@app.get("/health")
def health():
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"status": "ok"}


@app.post("/rerank", response_model=list[RerankResult])
def rerank(req: RerankRequest):
    if model is None or tokenizer is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    pairs = [[req.query, text] for text in req.texts]

    encoded = tokenizer(
        pairs,
        padding=True,
        truncation=req.truncate,
        max_length=MAX_LENGTH,
        return_tensors="pt",
    ).to(DEVICE)

    with torch.no_grad():
        logits = model(**encoded).logits
        if logits.shape[-1] == 1:
            scores = logits.squeeze(-1).float()
        else:
            scores = logits[:, 1].float()

    scores_list = scores.cpu().tolist()
    results = [
        RerankResult(index=i, score=float(s))
        for i, s in enumerate(scores_list)
    ]
    results.sort(key=lambda x: x.score, reverse=True)
    return results
