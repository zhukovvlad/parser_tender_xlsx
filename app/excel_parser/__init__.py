# app/excel_parser/__init__.py
"""
Excel Parser Module

This module provides utilities for parsing tender documents from Excel files.
It contains specialized functions for extracting various data structures:

- Headers and metadata extraction
- Contractor information parsing  
- Position and lot data processing
- Summary and additional information extraction
- Text sanitization and data postprocessing

The module is structured to handle complex Excel document layouts
commonly found in tender and procurement documents.
"""

# Core parsing functions
from .read_headers import read_headers
from .read_contractors import read_contractors
from .read_lots_and_boundaries import read_lots_and_boundaries
from .read_executer_block import read_executer_block

# Position and data extraction
from .get_positions import get_positions
from .get_lot_positions import get_lot_positions
from .get_proposals import get_proposals
from .get_summary import get_summary
from .get_additional_info import get_additional_info
from .get_items_dict import get_items_dict

# Utility functions
from .parse_contractor_row import parse_contractor_row
from .sanitize_text import sanitize_text, sanitize_object_and_address_text
from .postprocess import (
    normalize_lots_json_structure,
    replace_div0_with_null,
    _is_value_zero
)

# Navigation and helper utilities
from .find_row_by_first_column import find_row_by_first_column
from .build_merged_shape_map import build_merged_shape_map

__all__ = [
    # Core parsing
    'read_headers',
    'read_contractors', 
    'read_lots_and_boundaries',
    'read_executer_block',
    
    # Data extraction
    'get_positions',
    'get_lot_positions',
    'get_proposals',
    'get_summary',
    'get_additional_info',
    'get_items_dict',
    
    # Utilities
    'parse_contractor_row',
    'sanitize_text',
    'sanitize_object_and_address_text',
    'normalize_lots_json_structure',
    'replace_div0_with_null',
    'find_row_by_first_column',
    'build_merged_shape_map',
]
