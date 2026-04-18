import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction


class VectorStore:
    def __init__(self, db_path="./db", collection_name="knowledge"):
        self._embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        self._client = chromadb.PersistentClient(path=db_path)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=self._embedding_fn,
        )

    def add_documents(self, chunks, metadatas):
        """Add text chunks with metadata to the collection.

        Each chunk gets a unique ID based on source title + index.
        Skips chunks whose IDs already exist.
        """
        ids = []
        new_chunks = []
        new_metas = []

        for i, (chunk, meta) in enumerate(zip(chunks, metadatas)):
            doc_id = f"{meta.get('source', 'unknown')}_{i}"
            ids.append(doc_id)
            new_chunks.append(chunk)
            new_metas.append(meta)

        if not ids:
            return 0

        # Check which IDs already exist
        existing = self._collection.get(ids=ids)
        existing_ids = set(existing["ids"]) if existing["ids"] else set()

        # Filter to only new documents
        filtered = [
            (id_, chunk, meta)
            for id_, chunk, meta in zip(ids, new_chunks, new_metas)
            if id_ not in existing_ids
        ]

        if not filtered:
            return 0

        f_ids, f_chunks, f_metas = zip(*filtered)
        self._collection.add(
            ids=list(f_ids),
            documents=list(f_chunks),
            metadatas=list(f_metas),
        )
        return len(f_ids)

    def query(self, question, top_k=5):
        """Search for chunks similar to the question.

        Returns list of dicts: [{"text": ..., "metadata": ..., "distance": ...}]
        """
        results = self._collection.query(
            query_texts=[question],
            n_results=min(top_k, self._collection.count()),
        )

        if not results["documents"] or not results["documents"][0]:
            return []

        output = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            output.append({
                "text": doc,
                "metadata": meta,
                "distance": dist,
            })
        return output

    def get_stats(self):
        """Return collection statistics."""
        count = self._collection.count()
        # Get unique sources
        all_meta = self._collection.get()
        sources = set()
        if all_meta["metadatas"]:
            for m in all_meta["metadatas"]:
                sources.add(m.get("source", "unknown"))
        return {
            "total_chunks": count,
            "total_sources": len(sources),
            "sources": sorted(sources),
        }
