"""
Module 2 — Embeddings and Vector Retrieval
Embeds document chunks via ChromaDB with a configurable embedding function.
Default: BAAI/bge-base-en-v1.5 (via sentence-transformers, MIT license).
Fallback: ChromaDB's built-in ONNX all-MiniLM-L6-v2 (no PyTorch needed).
Stores and retrieves vectors using ChromaDB.
"""
import logging
import time
import uuid

import chromadb
from app.config import settings

logger = logging.getLogger(__name__)

# Lazy singletons
_chroma_client = None
_embedding_function = None


def _get_embedding_function():
    global _embedding_function
    if _embedding_function is not None:
        return _embedding_function

    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    _embedding_function = SentenceTransformerEmbeddingFunction(
        model_name=settings.embedding_model
    )
    logger.info(f"[Embeddings] Using {settings.embedding_model} (CPU)")
    return _embedding_function


def _sanitize_metadata(meta: dict) -> dict:
    """ChromaDB requires all metadata values to be str | int | float | bool.
    None values are omitted so they don't interfere with where-filter semantics."""
    sanitized = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            sanitized[k] = v
        else:
            sanitized[k] = str(v)
    return sanitized


def _get_chroma_client(retries: int = 2):
    """Get or create a persistent ChromaDB client with basic retry."""
    global _chroma_client
    if _chroma_client is not None:
        return _chroma_client
    for attempt in range(1 + retries):
        try:
            _chroma_client = chromadb.PersistentClient(
                path=settings.chroma_db_path,
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
            _chroma_client.heartbeat()
            return _chroma_client
        except Exception as e:
            _chroma_client = None
            if attempt < retries:
                wait = 1.0 * (attempt + 1)
                logger.warning(
                    f"[Embeddings] ChromaDB init attempt {attempt + 1} failed:"
                    f" {e} — retrying in {wait}s"
                )
                time.sleep(wait)
            else:
                logger.error(
                    f"[Embeddings] Failed to init ChromaDB after {retries + 1} attempts: {e}"
                )
    return None


def embed_and_store(chunks: list[dict], run_id: str) -> bool:
    """
    Embed text chunks and store in a ChromaDB collection specific to the run_id.
    Uses BAAI/bge-base-en-v1.5 if available, falls back to ChromaDB default ONNX.

    Verifies each batch by comparing collection count before and after write.
    Retries failed batches once.

    Returns True if at least one batch was stored successfully, False otherwise.
    """
    chroma_client = _get_chroma_client()
    if not chroma_client or not chunks:
        logger.warning(
            f"[Embeddings] No chroma client or empty chunks ({len(chunks)})"
        )
        return False

    collection_name = f"run_{run_id.replace('-', '_')}"

    try:
        # Delete any previous collection with same name (fresh run)
        try:
            chroma_client.delete_collection(name=collection_name)
        except Exception:
            pass  # first time — doesn't exist yet

        ef = _get_embedding_function()
        collection = chroma_client.get_or_create_collection(
            name=collection_name,
            embedding_function=ef,
            metadata={
                "embedding_model": settings.embedding_model,
                "created_at": str(time.time()),
            },
        )

        documents = [c["text"] for c in chunks]
        metadatas = [_sanitize_metadata(c["metadata"]) for c in chunks]
        ids = [str(uuid.uuid4()) for _ in chunks]

        batch_size = 100
        stored_count = 0
        expected_total = len(documents)

        for i in range(0, expected_total, batch_size):
            batch_end = min(i + batch_size, expected_total)
            batch_docs = documents[i:batch_end]
            batch_metas = metadatas[i:batch_end]
            batch_ids = ids[i:batch_end]
            batch_label = f"{i // batch_size}"

            # Count before write for verification
            count_before = collection.count()

            for retry in range(2):  # at most 1 retry
                try:
                    collection.add(
                        documents=batch_docs,
                        metadatas=batch_metas,
                        ids=batch_ids,
                    )
                    break
                except Exception as batch_err:
                    if retry < 1:
                        logger.warning(
                            f"[Embeddings] Batch {batch_label} failed (retrying): {batch_err}"
                        )
                        time.sleep(1.0)
                    else:
                        logger.error(
                            f"[Embeddings] Batch {batch_label} failed after retry: {batch_err}"
                        )

            # Verify actual count increased by the expected amount
            count_after = collection.count()
            added = count_after - count_before
            if added == len(batch_ids):
                stored_count += added
            else:
                logger.warning(
                    f"[Embeddings] Batch {batch_label}: expected {len(batch_ids)} docs,"
                    f" count delta={added} — possible silent truncation"
                )
                stored_count += max(0, added)

        if stored_count == 0:
            logger.error("[Embeddings] All batches failed — no chunks stored.")
            return False

        logger.info(
            f"[Embeddings] Stored {stored_count}/{expected_total} chunks"
            f" in {collection_name}"
            f" ({'verified' if stored_count == expected_total else str(expected_total - stored_count) + ' missing'})"
        )
        return stored_count > 0

    except Exception as e:
        logger.error(f"[Embeddings] Failed to store chunks: {e}", exc_info=True)
        return False


def retrieve_top_k(
    query: str,
    run_id: str,
    k: int = 50,
    indicator_id: str = "",
    pillar_id: str = "",
    where_filter: dict | None = None,
) -> list[dict]:
    """
    Retrieve the top K most relevant chunks for a given query.

    Args:
        query: The search question.
        run_id: The analysis run UUID.
        k: Number of chunks to retrieve.
        indicator_id: If provided, filter to this indicator.
        pillar_id: If provided (no indicator_id), filter to this pillar.
        where_filter: Optional explicit ChromaDB where filter (overrides indicator/pillar).

    Returns:
        List of chunks with 'text' and 'metadata'.
    """
    chroma_client = _get_chroma_client()
    if not chroma_client:
        return []

    collection_name = f"run_{run_id.replace('-', '_')}"

    try:
        ef = _get_embedding_function()

        # Use get_collection to avoid creating empty collections on read
        try:
            collection = chroma_client.get_collection(
                name=collection_name,
                embedding_function=ef,
            )
        except ValueError:
            logger.warning(
                f"[Embeddings] Collection '{collection_name}' not found — "
                f"vector retrieval skipped"
            )
            return []

        # Validate embedding model version
        col_meta = getattr(collection, "metadata", None) or {}
        stored_model = col_meta.get("embedding_model")
        if stored_model and stored_model != settings.embedding_model:
            logger.warning(
                f"[Embeddings] Model mismatch: collection built with '{stored_model}', "
                f"current model is '{settings.embedding_model}' — dimensions may differ"
            )

        collection_count = collection.count()
        if collection_count == 0:
            logger.warning(
                f"[Embeddings] Collection '{collection_name}' is empty."
            )
            return []

        effective_filter = where_filter
        if effective_filter is None:
            if indicator_id:
                effective_filter = {"indicator_id": indicator_id}
            elif pillar_id:
                effective_filter = {"pillar_id": pillar_id}

        # If filtered, verify at least one doc matches the filter
        # (collection.count(where=...) is not available in older ChromaDB versions)
        if effective_filter:
            sample = collection.get(where=effective_filter, limit=1)
            if not sample or not sample.get("ids"):
                logger.warning(
                    f"[Embeddings] Filter {effective_filter} matched 0/{collection_count} "
                    f"docs in '{collection_name}' — returning empty"
                )
                return []
            n_results = max(1, min(k, collection_count))
        else:
            n_results = max(1, min(k, collection_count))

        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=effective_filter,
        )

        retrieved = []
        if results and results.get("documents"):
            docs = results["documents"][0]
            # Log average distance if available
            if results.get("distances"):
                avg_dist = sum(results["distances"][0]) / len(results["distances"][0])
                logger.debug(
                    f"[Embeddings] Avg vector distance: {avg_dist:.4f} "
                    f"(lower = more similar) for {len(results['distances'][0])} results"
                )

            # Safely extract metadata list — never rely on zip() for alignment
            raw_metas = results.get("metadatas")
            if raw_metas and isinstance(raw_metas, list) and len(raw_metas) > 0:
                metas = raw_metas[0]
                if not isinstance(metas, list):
                    metas = [metas] if metas is not None else []
            else:
                metas = []

            for idx, doc in enumerate(docs):
                meta = (metas[idx] if idx < len(metas) else None) or {}
                retrieved.append({"text": doc, "metadata": meta})

        logger.info(
            f"[Embeddings] Retrieved {len(retrieved)}/{n_results} vector chunks"
            f" (collection={collection_count}) for query='{query[:60]}'"
        )
        return retrieved

    except Exception as e:
        logger.error(
            f"[Embeddings] Retrieval failed: {e}", exc_info=True
        )
        return []


def cleanup_collection(run_id: str) -> None:
    """Delete the ChromaDB collection after analysis."""
    chroma_client = _get_chroma_client()
    if not chroma_client:
        return
    collection_name = f"run_{run_id.replace('-', '_')}"
    try:
        chroma_client.delete_collection(name=collection_name)
        logger.info(f"[Embeddings] Deleted collection {collection_name}")
    except Exception:
        pass


def rerank_chunks(chunks: list[dict], query: str, top_k: int = 20) -> list[dict]:
    """Rerank chunks by cosine similarity between query and chunk embeddings.
    Uses the same embedding model as the rest of the pipeline.
    Falls back to keyword-score ranking if embedding fails.
    """
    if not chunks or not query:
        return chunks[:top_k]

    try:
        ef = _get_embedding_function()
        query_emb = ef([query])[0]
        chunk_texts = [c.get("text", "") for c in chunks]
        chunk_embs = ef(chunk_texts)

        import numpy as np
        query_vec = np.array(query_emb, dtype=np.float32)
        scores = []
        for emb in chunk_embs:
            chunk_vec = np.array(emb, dtype=np.float32)
            dot = float(np.dot(query_vec, chunk_vec))
            qnorm = float(np.linalg.norm(query_vec))
            cnorm = float(np.linalg.norm(chunk_vec))
            if qnorm > 0 and cnorm > 0:
                scores.append(dot / (qnorm * cnorm))
            else:
                scores.append(0.0)

        ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
        return [c for _, c in ranked[:top_k]]
    except Exception as e:
        logger.warning(f"[Embeddings] Rerank failed ({e}) — returning top {top_k} as-is")
        return chunks[:top_k]
