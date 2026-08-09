"""
Lightweight local RAG index over the synthetic policy PDFs.

Design note: this uses TF-IDF + cosine similarity rather than a neural
embedding model (sentence-transformers / OpenAI / Cohere embeddings) so the
whole app runs fully offline with zero external embedding API calls or model
downloads. The retriever interface (`.search(query, k)`) is the same shape
you'd get from a real vector store, so swapping in Chroma/FAISS + a hosted
or local embedding model later is a drop-in change in this one file only —
nothing in the agent layer needs to know the difference.
"""
import os
import pickle
from dataclasses import dataclass
from typing import List

from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "pdfs")
INDEX_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "rag_index.pkl")

CHUNK_SIZE = 700       # characters
CHUNK_OVERLAP = 120


@dataclass
class Chunk:
    doc_id: str
    doc_title: str
    section: str
    text: str


def _extract_pages(pdf_path: str) -> List[str]:
    reader = PdfReader(pdf_path)
    return [page.extract_text() or "" for page in reader.pages]


def _chunk_text(text: str, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> List[str]:
    text = " ".join(text.split())
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap
    return [c for c in chunks if len(c.strip()) > 40]


def build_index() -> None:
    chunks: List[Chunk] = []
    for fname in sorted(os.listdir(PDF_DIR)):
        if not fname.lower().endswith(".pdf"):
            continue
        path = os.path.join(PDF_DIR, fname)
        pages = _extract_pages(path)
        full_text = "\n".join(pages)
        title = fname.replace("_", " ").replace(".pdf", "")
        for i, ch in enumerate(_chunk_text(full_text)):
            chunks.append(Chunk(doc_id=fname, doc_title=title, section=f"chunk {i+1}", text=ch))

    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=8000)
    matrix = vectorizer.fit_transform([c.text for c in chunks])

    with open(INDEX_PATH, "wb") as f:
        pickle.dump({"chunks": chunks, "vectorizer": vectorizer, "matrix": matrix}, f)

    print(f"Indexed {len(chunks)} chunks from {len(os.listdir(PDF_DIR))} PDFs -> {INDEX_PATH}")


class RagIndex:
    """Loads the persisted TF-IDF index and exposes a `.search()` method."""

    _instance = None

    def __init__(self):
        if not os.path.exists(INDEX_PATH):
            build_index()
        with open(INDEX_PATH, "rb") as f:
            data = pickle.load(f)
        self.chunks: List[Chunk] = data["chunks"]
        self.vectorizer: TfidfVectorizer = data["vectorizer"]
        self.matrix = data["matrix"]

    @classmethod
    def get(cls) -> "RagIndex":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def search(self, query: str, k: int = 4) -> List[dict]:
        q_vec = self.vectorizer.transform([query])
        sims = cosine_similarity(q_vec, self.matrix)[0]
        top_idx = sims.argsort()[::-1][:k]
        results = []
        for idx in top_idx:
            if sims[idx] <= 0:
                continue
            c = self.chunks[idx]
            results.append({
                "doc_title": c.doc_title,
                "section": c.section,
                "text": c.text,
                "score": round(float(sims[idx]), 4),
            })
        return results


if __name__ == "__main__":
    build_index()
    idx = RagIndex.get()
    for r in idx.search("what happens if a worker exceeds 10 hours in a day"):
        print(r["doc_title"], r["section"], r["score"])
        print(" ", r["text"][:150], "...")
