"""Prefetch the local embedding and reranking models used by the RAG pipeline."""

from sentence_transformers import CrossEncoder, SentenceTransformer

from backend.app.rag.models import EMBED_MODEL_NAME, RERANKER_MODEL_NAME
from backend.app.router.config import load_router_config


def main() -> None:
    router_config = load_router_config()
    SentenceTransformer(
        router_config.model_name,
        revision=router_config.model_revision,
        device="cpu",
    )
    SentenceTransformer(EMBED_MODEL_NAME, device="cpu")
    CrossEncoder(
        RERANKER_MODEL_NAME,
        device="cpu",
        local_files_only=False,
    )
    print(f"RAG models available locally: {EMBED_MODEL_NAME}, {RERANKER_MODEL_NAME}")


if __name__ == "__main__":
    main()
