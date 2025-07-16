"""
Validation utilities for file uploads and data processing.
"""

import hashlib
import mimetypes
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile


class FileValidationError(Exception):
    """Exception raised when file validation fails."""

    pass


def validate_file_extension(filename: str, allowed_extensions: list[str]) -> bool:
    """
    Validate file extension.

    Args:
        filename: Name of the file
        allowed_extensions: List of allowed extensions (e.g., ['.xlsx', '.xls'])

    Returns:
        True if extension is allowed

    Raises:
        FileValidationError: If extension is not allowed
    """
    if not filename:
        raise FileValidationError("Filename cannot be empty")

    file_extension = Path(filename).suffix.lower()
    if file_extension not in allowed_extensions:
        raise FileValidationError(
            f"File extension '{file_extension}' not allowed. "
            f"Allowed extensions: {', '.join(allowed_extensions)}"
        )

    return True


def validate_file_size(file_size: int, max_size: int) -> bool:
    """
    Validate file size.

    Args:
        file_size: Size of the file in bytes
        max_size: Maximum allowed size in bytes

    Returns:
        True if size is acceptable

    Raises:
        FileValidationError: If file is too large
    """
    if file_size > max_size:
        max_size_mb = max_size / (1024 * 1024)
        file_size_mb = file_size / (1024 * 1024)
        raise FileValidationError(
            f"File size ({file_size_mb:.1f}MB) exceeds maximum allowed size ({max_size_mb:.1f}MB)"
        )

    return True


def validate_mime_type(file: UploadFile) -> bool:
    """
    Validate MIME type of uploaded file.

    Args:
        file: FastAPI UploadFile object

    Returns:
        True if MIME type is acceptable

    Raises:
        FileValidationError: If MIME type is not acceptable
    """
    allowed_mime_types = [
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
        "application/vnd.ms-excel",  # .xls
    ]

    # Check declared content type
    if file.content_type not in allowed_mime_types:
        # Try to guess from filename
        guessed_type, _ = mimetypes.guess_type(file.filename or "")
        if guessed_type not in allowed_mime_types:
            raise FileValidationError(
                f"MIME type '{file.content_type}' not allowed. "
                f"Expected Excel file (.xlsx or .xls)"
            )

    return True


async def validate_upload_file(
    file: UploadFile, max_size: int, allowed_extensions: list[str]
) -> dict[str, str]:
    """
    Comprehensive validation of uploaded file.

    Args:
        file: FastAPI UploadFile object
        max_size: Maximum file size in bytes
        allowed_extensions: List of allowed file extensions

    Returns:
        Dictionary with file metadata

    Raises:
        HTTPException: If validation fails
    """
    try:
        # Basic checks
        if not file.filename:
            raise FileValidationError("No filename provided")

        # Extension validation
        validate_file_extension(file.filename, allowed_extensions)

        # MIME type validation
        validate_mime_type(file)

        # Read file content for size validation and hash calculation
        content = await file.read()
        await file.seek(0)  # Reset file pointer

        # Size validation
        validate_file_size(len(content), max_size)

        # Calculate file hash for deduplication
        file_hash = hashlib.sha256(content).hexdigest()

        return {
            "filename": file.filename,
            "size": len(content),
            "hash": file_hash,
            "content_type": file.content_type or "unknown",
        }

    except FileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File validation error: {str(e)}")


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to prevent path traversal attacks.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename
    """
    # Get just the filename without any path components
    safe_filename = Path(filename).name

    # Remove any potentially dangerous characters
    dangerous_chars = '<>:"/\\|?*'
    for char in dangerous_chars:
        safe_filename = safe_filename.replace(char, "_")

    # Remove dots at the beginning (hidden files and path traversal)
    while safe_filename.startswith("."):
        safe_filename = safe_filename[1:]

    # Ensure filename is not empty after sanitization
    if not safe_filename or safe_filename.isspace():
        safe_filename = "unnamed_file"

    return safe_filename
