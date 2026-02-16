"""Parse and validate search responses."""

import json
from typing import Any, Dict, List


class SearchResponseParser:
    """Parse and validate RAG search responses."""
    
    @staticmethod
    def parse_search_results(response_text: str) -> List[Dict[str, Any]]:
        """Parse JSON response from model."""
        if not response_text:
            return []
        
        try:
            result_json = json.loads(response_text)
        except json.JSONDecodeError:
            return []
        
        # Normalize to list
        if isinstance(result_json, dict):
            result_json = [result_json]
        
        # Validate and normalize results
        valid_results = []
        for item in result_json:
            if "catalog_id" in item:
                if "score" not in item:
                    item["score"] = 0.0
                valid_results.append(item)
        
        return valid_results
