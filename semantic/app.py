import os
from contextlib import asynccontextmanager
from threading import Lock

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

EMBEDDING_MODEL = 'BAAI/bge-m3'
RERANKER_MODEL = 'BAAI/bge-reranker-v2-m3'
EMBEDDING_REVISION = os.getenv('BGE_M3_REVISION', '5617a9f61b028005a4858fdac845db406aefb181')
RERANKER_REVISION = os.getenv(
    'BGE_RERANKER_REVISION', '953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e',
)
_IGNORED_MODEL_FILES = ['onnx/**', 'imgs/**', '*.onnx', 'README.md', '.gitattributes']
_inference_lock = Lock()


class RankingRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1500)
    documents: list[str] = Field(min_length=1, max_length=32)

    @field_validator('documents')
    @classmethod
    def validate_documents(cls, documents):
        if any(not document.strip() or len(document) > 2000 for document in documents):
            raise ValueError('Documents must contain 1-2000 characters')
        return documents


@asynccontextmanager
async def lifespan(app: FastAPI):
    from FlagEmbedding import BGEM3FlagModel, FlagReranker
    from huggingface_hub import snapshot_download

    torch.set_num_threads(max(1, int(os.getenv('OMP_NUM_THREADS', '4'))))
    embedding_path = snapshot_download(
        repo_id=EMBEDDING_MODEL,
        revision=EMBEDDING_REVISION,
        ignore_patterns=_IGNORED_MODEL_FILES,
        max_workers=4,
    )
    reranker_path = snapshot_download(
        repo_id=RERANKER_MODEL,
        revision=RERANKER_REVISION,
        ignore_patterns=_IGNORED_MODEL_FILES,
        max_workers=4,
    )
    app.state.embedder = BGEM3FlagModel(
        embedding_path,
        use_fp16=False,
        devices='cpu',
        normalize_embeddings=True,
        trust_remote_code=False,
    )
    app.state.reranker = FlagReranker(
        reranker_path,
        use_fp16=False,
        devices='cpu',
        trust_remote_code=False,
    )
    yield


app = FastAPI(title='UrbexFinder local semantic ranking', lifespan=lifespan)


@app.get('/health')
def health():
    return {'status': 'ok' if hasattr(app.state, 'reranker') else 'loading'}


@app.post('/rank')
def rank(request: RankingRequest):
    if not hasattr(app.state, 'reranker'):
        raise HTTPException(status_code=503, detail='Models are loading')

    try:
        with _inference_lock:
            encoded = app.state.embedder.encode(
                [request.query, *request.documents],
                batch_size=8,
                max_length=512,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )['dense_vecs']
            embedding_scores = np.asarray(encoded[1:]) @ np.asarray(encoded[0])
            pairs = [[request.query, document] for document in request.documents]
            reranker_scores = np.atleast_1d(app.state.reranker.compute_score(
                pairs,
                batch_size=8,
                normalize=True,
            ))
        return {
            'scores': [
                {
                    'embedding_score': float(embedding_score),
                    'reranker_score': float(reranker_score),
                }
                for embedding_score, reranker_score in zip(
                    embedding_scores, reranker_scores, strict=True,
                )
            ],
        }
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail='Semantic ranking failed') from exc
