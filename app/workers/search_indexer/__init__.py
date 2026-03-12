# app/workers/search_indexer/__init__.py
"""
Search Indexer воркер для эмбеддинга, дедупликации и активации
каталожных позиций.
"""

from .worker import SearchIndexerWorker

__all__ = [
    "SearchIndexerWorker",
]
