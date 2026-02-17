"""Configuration for Google RAG module."""

import os
from dataclasses import dataclass


@dataclass
class RagConfig:
    """Configuration for RAG File Search."""
    
    api_key: str
    store_id: str
    store_display_name: str
    model_name: str
    max_tokens_per_chunk: int = 512
    max_overlap_tokens: int = 0
    operation_timeout: int = 600
    max_retries: int = 3
    max_search_results: int = 3
    
    @classmethod
    def from_env(cls) -> "RagConfig":
        """Load configuration from environment variables."""
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY не установлен в .env")
        
        return cls(
            api_key=api_key,
            store_id=os.getenv("GOOGLE_RAG_STORE_ID", "rag-catalog-store"),
            store_display_name="Tenders Catalog Store",
            model_name=os.getenv("GOOGLE_RAG_MODEL", "gemini-2.5-flash"),
        )
