from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel
import os

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)


class Settings(BaseModel):
    llm_model: str
    llm_api_key: str
    llm_base_url: str
    embedding_model: str
    ncbi_email: str
    ncbi_api_key: str

    pubmed_timeout: float = 30.0
    llm_timeout: float = 120.0
    target_pmids: int = 50
    retmax_per_query: int = 25
    abstract_max_chars: int = 1200

    fulltext_max_articles: int = 10
    fulltext_max_chars: int = 80000
    rag_top_k: int = 12
    chunk_size: int = 1000
    chunk_overlap: int = 150


def get_settings() -> Settings:
    return Settings(
        llm_model=os.getenv("LLM_MODEL", "deepseek-v4.1-flash"),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_base_url=os.getenv("LLM_BASE_URL", "").rstrip("/"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-v3"),
        ncbi_email=os.getenv("NCBI_EMAIL", ""),
        ncbi_api_key=os.getenv("NCBI_API_KEY", ""),
        fulltext_max_articles=int(os.getenv("FULLTEXT_MAX_ARTICLES", "10")),
        fulltext_max_chars=int(os.getenv("FULLTEXT_MAX_CHARS", "80000")),
        rag_top_k=int(os.getenv("RAG_TOP_K", "12")),
        chunk_size=int(os.getenv("CHUNK_SIZE", "1000")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "150")),
    )
