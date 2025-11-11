# app/workers/rag_catalog/__init__.py
"""
RAG Catalog воркер для сопоставления и дедупликации позиций.
"""

from .worker import RagWorker

__all__ = [
    "RagWorker",
]
