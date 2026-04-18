from openai import OpenAI
from bot.prompts import SYSTEM_PROMPT
import config


class RAGBot:
    def __init__(self, vector_store, openai_client=None):
        self._store = vector_store
        self._client = openai_client or OpenAI(api_key=config.OPENAI_API_KEY)
        self._model = config.OPENAI_MODEL
        self._top_k = config.TOP_K_RESULTS

    def ask(self, question, chat_history=None):
        """Retrieve relevant context and generate an answer.

        Returns a dict: {"answer": str, "sources": list[str]}
        """
        if chat_history is None:
            chat_history = []

        # Retrieve relevant chunks
        results = self._store.query(question, top_k=self._top_k)

        if not results:
            return {
                "answer": "I don't have enough information in my knowledge base to answer that question.",
                "sources": [],
            }

        # Build context and source list
        context_parts = []
        sources = []
        for i, r in enumerate(results, 1):
            source = r["metadata"].get("source", "Unknown")
            context_parts.append(f"[{i}] {r['text']}")
            if source not in sources:
                sources.append(source)

        context = "\n\n".join(context_parts)
        sources_str = "\n".join(f"- {s}" for s in sources)

        system_msg = SYSTEM_PROMPT.format(context=context, sources=sources_str)

        messages = [
            {"role": "system", "content": system_msg},
            *chat_history,
            {"role": "user", "content": question},
        ]

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        answer = response.choices[0].message.content

        return {"answer": answer, "sources": sources}
