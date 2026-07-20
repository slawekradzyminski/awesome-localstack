from __future__ import annotations

import math
import os
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from transformers import AutoTokenizer, GPT2LMHeadModel

MODEL_ID = os.getenv("GPT2_MODEL_ID", "openai-community/gpt2")
MODEL_REVISION = os.getenv("GPT2_MODEL_REVISION", "607a30d783dfa663caf39e06633721c8d4cfcd7e")
MAX_TOKENS = 32
SAMPLED_DIMENSIONS = 24


class TraceRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=800)
    layer: int = Field(default=0, ge=0, le=11)
    head: int = Field(default=0, ge=0, le=11)
    selected_token_index: int | None = Field(default=None, alias="selectedTokenIndex")


class EmbeddingSpaceRequest(BaseModel):
    query: str | None = Field(default=None, min_length=1, max_length=80)
    token_id: int | None = Field(default=None, ge=0, le=50256, alias="tokenId")
    neighbor_count: int = Field(default=14, ge=6, le=24, alias="neighborCount")


def _round(value: float, digits: int = 7) -> float:
    return round(float(value), digits)


def _numbers(tensor: torch.Tensor) -> list[float]:
    return [_round(value) for value in tensor.detach().cpu().tolist()]


def _matrix(tensor: torch.Tensor) -> list[list[float]]:
    return [_numbers(row) for row in tensor]


def _sample(tensor: torch.Tensor, dimensions: torch.Tensor) -> list[float]:
    return _numbers(tensor.index_select(-1, dimensions))


def _primary_tensor(output: torch.Tensor | tuple[torch.Tensor, ...]) -> torch.Tensor:
    """Normalize Transformer module outputs across supported library majors."""
    return output if isinstance(output, torch.Tensor) else output[0]


def _prediction_rows(tokenizer: AutoTokenizer, logits: torch.Tensor, count: int = 5) -> list[dict[str, Any]]:
    probabilities = torch.softmax(logits, dim=-1)
    top_probabilities, top_ids = torch.topk(probabilities, k=count)
    top_logits = logits.index_select(0, top_ids)
    return [
        {
            "rank": rank + 1,
            "id": int(token_id),
            "token": tokenizer.decode([int(token_id)]),
            "probability": _round(top_probabilities[rank]),
            "logit": _round(top_logits[rank]),
        }
        for rank, token_id in enumerate(top_ids.tolist())
    ]


def _local_pca(vectors: torch.Tensor) -> torch.Tensor:
    centered = vectors - vectors.mean(dim=0, keepdim=True)
    _, _, right = torch.linalg.svd(centered, full_matrices=False)
    coordinates = centered @ right[:3].transpose(0, 1)
    scale = coordinates.abs().amax().clamp_min(1e-8)
    return coordinates / scale


def _global_pca(vectors: torch.Tensor) -> torch.Tensor:
    centered = vectors - vectors.mean(dim=0, keepdim=True)
    with torch.random.fork_rng():
        torch.manual_seed(0)
        _, _, components = torch.pca_lowrank(centered, q=3, center=False, niter=4)
    coordinates = centered @ components[:, :3]
    scale = torch.quantile(coordinates.abs(), 0.995, dim=0).clamp_min(1e-8)
    return (coordinates / scale).clamp(-1.25, 1.25)


class Gpt2Inspector:
    def __init__(self) -> None:
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
        self.model = GPT2LMHeadModel.from_pretrained(
            MODEL_ID,
            revision=MODEL_REVISION,
            attn_implementation="eager",
        )
        self.model.eval()
        self.lock = Lock()
        self.embedding_matrix = self.model.transformer.wte.weight.detach()
        self.normalized_embedding_matrix = torch.nn.functional.normalize(self.embedding_matrix.float(), dim=1)
        self.embedding_forest_cache: dict[str, Any] | None = None

    def embedding_space(self, request: EmbeddingSpaceRequest) -> dict[str, Any]:
        if request.token_id is not None:
            selected_id = request.token_id
        elif request.query:
            query = request.query.strip()
            candidates = [f" {query}", query] if not request.query.startswith((" ", "\n", "\t")) else [request.query]
            single_tokens = [token_ids[0] for candidate in candidates if len(token_ids := self.tokenizer.encode(candidate, add_special_tokens=False)) == 1]
            if not single_tokens:
                raise HTTPException(status_code=400, detail="Enter text that maps to one GPT-2 token")
            selected_id = single_tokens[0]
        else:
            raise HTTPException(status_code=400, detail="Provide a query or tokenId")

        with self.lock, torch.inference_mode():
            selected_vector = self.normalized_embedding_matrix[selected_id]
            similarities = self.normalized_embedding_matrix @ selected_vector
            _, nearest_ids = torch.topk(similarities, k=request.neighbor_count + 1)
            neighbor_ids = [int(token_id) for token_id in nearest_ids.tolist() if int(token_id) != selected_id][:request.neighbor_count]
            point_ids = [selected_id, *neighbor_ids]
            local_vectors = self.embedding_matrix[point_ids].float()
            coordinates = _local_pca(local_vectors)

        points = []
        for index, token_id in enumerate(point_ids):
            coordinate = coordinates[index]
            points.append({
                "id": token_id,
                "text": self.tokenizer.decode([token_id]),
                "vocabularyForm": self.tokenizer.convert_ids_to_tokens(token_id),
                "similarity": _round(similarities[token_id]),
                "x": _round(coordinate[0]),
                "y": _round(coordinate[1]),
                "z": _round(coordinate[2]),
            })

        return {
            "source": "gpt2-embedding-table",
            "modelLabel": MODEL_ID,
            "modelRevision": MODEL_REVISION[:8],
            "vocabularySize": self.model.config.vocab_size,
            "hiddenSize": self.model.config.n_embd,
            "selectedTokenId": selected_id,
            "projection": "local-pca-3",
            "points": points,
        }

    def embedding_forest(self) -> dict[str, Any]:
        with self.lock, torch.inference_mode():
            if self.embedding_forest_cache is not None:
                return self.embedding_forest_cache
            coordinates = _global_pca(self.embedding_matrix.float()).cpu()

        points = [
            {
                "id": token_id,
                "text": self.tokenizer.decode([token_id]),
                "x": _round(coordinate[0], 5),
                "y": _round(coordinate[1], 5),
                "z": _round(coordinate[2], 5),
            }
            for token_id, coordinate in enumerate(coordinates)
        ]
        response = {
            "source": "gpt2-embedding-table",
            "modelLabel": MODEL_ID,
            "modelRevision": MODEL_REVISION[:8],
            "vocabularySize": self.model.config.vocab_size,
            "hiddenSize": self.model.config.n_embd,
            "projection": "global-pca-3",
            "points": points,
        }
        with self.lock:
            self.embedding_forest_cache = response
        return response

    def trace(self, request: TraceRequest) -> dict[str, Any]:
        encoded = self.tokenizer(request.prompt, return_tensors="pt", add_special_tokens=False)
        input_ids = encoded["input_ids"]
        token_count = input_ids.shape[1]
        if token_count == 0:
            raise HTTPException(status_code=400, detail="Prompt must produce at least one GPT-2 token")
        if token_count > MAX_TOKENS:
            raise HTTPException(status_code=400, detail=f"Prompt may contain at most {MAX_TOKENS} GPT-2 tokens")

        selected_index = request.selected_token_index if request.selected_token_index is not None else token_count - 1
        if selected_index < 0 or selected_index >= token_count:
            raise HTTPException(status_code=400, detail="Selected token index is outside the tokenized prompt")

        captures: dict[str, torch.Tensor] = {}
        block = self.model.transformer.h[request.layer]

        def capture_pre(_module: torch.nn.Module, args: tuple[Any, ...]) -> None:
            captures["residual_pre"] = args[0].detach()

        def capture_qkv(_module: torch.nn.Module, _args: tuple[Any, ...], output: torch.Tensor) -> None:
            captures["qkv"] = output.detach()

        def capture_attention(
            _module: torch.nn.Module,
            _args: tuple[Any, ...],
            output: torch.Tensor | tuple[torch.Tensor, ...],
        ) -> None:
            captures["attention_output"] = _primary_tensor(output).detach()

        def capture_mlp(_module: torch.nn.Module, _args: tuple[Any, ...], output: torch.Tensor) -> None:
            captures["mlp_output"] = output.detach()

        def capture_block(
            _module: torch.nn.Module,
            _args: tuple[Any, ...],
            output: torch.Tensor | tuple[torch.Tensor, ...],
        ) -> None:
            captures["residual_post"] = _primary_tensor(output).detach()

        handles = [
            block.register_forward_pre_hook(capture_pre),
            block.attn.c_attn.register_forward_hook(capture_qkv),
            block.attn.register_forward_hook(capture_attention),
            block.mlp.register_forward_hook(capture_mlp),
            block.register_forward_hook(capture_block),
        ]

        try:
            with self.lock, torch.inference_mode():
                outputs = self.model(
                    input_ids=input_ids,
                    use_cache=False,
                    output_attentions=True,
                    return_dict=True,
                )
        finally:
            for handle in handles:
                handle.remove()

        hidden_size = self.model.config.n_embd
        head_dimension = hidden_size // self.model.config.n_head
        qkv = captures["qkv"][0]
        queries, keys, values = qkv.split(hidden_size, dim=-1)
        queries = queries.reshape(token_count, self.model.config.n_head, head_dimension)[:, request.head]
        keys = keys.reshape(token_count, self.model.config.n_head, head_dimension)[:, request.head]
        values = values.reshape(token_count, self.model.config.n_head, head_dimension)[:, request.head]

        reconstructed_scores = queries @ keys.transpose(0, 1) / math.sqrt(head_dimension)
        causal_mask = torch.triu(torch.ones(token_count, token_count, dtype=torch.bool), diagonal=1)
        masked_scores = reconstructed_scores.masked_fill(causal_mask, torch.finfo(reconstructed_scores.dtype).min)
        reconstructed_attention = torch.softmax(masked_scores, dim=-1)
        captured_attention = outputs.attentions[request.layer][0, request.head]
        weighted_value = captured_attention[selected_index] @ values

        residual_pre = captures["residual_pre"][0, selected_index]
        attention_output = captures["attention_output"][0, selected_index]
        residual_mid = residual_pre + attention_output
        mlp_output = captures["mlp_output"][0, selected_index]
        residual_post = captures["residual_post"][0, selected_index]

        def logit_lens(state: torch.Tensor) -> list[dict[str, Any]]:
            with torch.inference_mode():
                normalized = self.model.transformer.ln_f(state)
                return _prediction_rows(self.tokenizer, self.model.lm_head(normalized))

        positions = torch.arange(token_count)
        token_embedding = self.model.transformer.wte(input_ids)[0, selected_index]
        position_embedding = self.model.transformer.wpe(positions)[selected_index]
        sample_dimensions = torch.linspace(0, hidden_size - 1, SAMPLED_DIMENSIONS).round().long()

        tokens = [
            {
                "index": index,
                "id": int(token_id),
                "text": self.tokenizer.decode([int(token_id)]),
                "vocabularyForm": self.tokenizer.convert_ids_to_tokens(int(token_id)),
            }
            for index, token_id in enumerate(input_ids[0].tolist())
        ]
        predictions = _prediction_rows(self.tokenizer, outputs.logits[0, selected_index])

        return {
            "source": "gpt2-live",
            "modelLabel": MODEL_ID,
            "modelRevision": MODEL_REVISION[:8],
            "prompt": request.prompt,
            "layer": request.layer,
            "head": request.head,
            "selectedTokenIndex": selected_index,
            "layerCount": self.model.config.n_layer,
            "headCount": self.model.config.n_head,
            "headDimension": head_dimension,
            "hiddenSize": hidden_size,
            "tokens": tokens,
            "query": _numbers(queries[selected_index]),
            "keys": _matrix(keys),
            "values": _matrix(values),
            "rawScoreRow": _numbers(reconstructed_scores[selected_index]),
            "attentionRow": _numbers(captured_attention[selected_index]),
            "attentionMatrix": _matrix(captured_attention),
            "weightedValue": _numbers(weighted_value),
            "sampledDimensions": [int(value) for value in sample_dimensions.tolist()],
            "tokenEmbedding": _sample(token_embedding, sample_dimensions),
            "positionEmbedding": _sample(position_embedding, sample_dimensions),
            "residualPre": _sample(residual_pre, sample_dimensions),
            "attentionOutput": _sample(attention_output, sample_dimensions),
            "residualMid": _sample(residual_mid, sample_dimensions),
            "mlpOutput": _sample(mlp_output, sample_dimensions),
            "residualPost": _sample(residual_post, sample_dimensions),
            "predictions": predictions,
            "logitLens": {
                "pre": logit_lens(residual_pre),
                "attention": logit_lens(residual_mid),
                "mlp": logit_lens(residual_post),
            },
            "checks": {
                "attentionRowSum": _round(captured_attention[selected_index].sum()),
                "futureAttentionMass": _round(captured_attention[selected_index, selected_index + 1 :].sum()),
                "attentionReconstructionMaxError": _round(
                    (captured_attention - reconstructed_attention).abs().max()
                ),
                "residualMidMaxError": _round(
                    (residual_mid - (residual_pre + attention_output)).abs().max()
                ),
                "residualPostMaxError": _round(
                    (residual_post - (residual_mid + mlp_output)).abs().max()
                ),
            },
        }


inspector: Gpt2Inspector | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global inspector
    inspector = Gpt2Inspector()
    yield
    inspector = None


app = FastAPI(title="GPT-2 Learning Inspector", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, Any]:
    if inspector is None:
        raise HTTPException(status_code=503, detail="GPT-2 is still loading")
    return {
        "status": "ready",
        "modelLabel": MODEL_ID,
        "modelRevision": MODEL_REVISION[:8],
        "layerCount": inspector.model.config.n_layer,
        "headCount": inspector.model.config.n_head,
        "maxTokens": MAX_TOKENS,
    }


@app.post("/trace")
def trace(request: TraceRequest) -> dict[str, Any]:
    if inspector is None:
        raise HTTPException(status_code=503, detail="GPT-2 is still loading")
    return inspector.trace(request)


@app.post("/embedding-space")
def embedding_space(request: EmbeddingSpaceRequest) -> dict[str, Any]:
    if inspector is None:
        raise HTTPException(status_code=503, detail="GPT-2 is still loading")
    return inspector.embedding_space(request)


@app.get("/embedding-forest")
def embedding_forest() -> dict[str, Any]:
    if inspector is None:
        raise HTTPException(status_code=503, detail="GPT-2 is still loading")
    return inspector.embedding_forest()
