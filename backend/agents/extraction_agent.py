"""Extraction agent wrapper around document ingestion."""

from pathlib import Path
from typing import Any

from backend.ingestion.document_loader import (
    extract_document_text,
    load_extracted_document,
    save_extracted_document,
)


class ExtractionAgent:
    """Extracts page-referenced text and headings from validated legal documents."""

    def run(
        self,
        file_path: Path,
        document_id: str,
        filename: str,
        file_type: str,
        extracted_dir: Path,
    ) -> dict[str, Any]:
        extracted = extract_document_text(
            file_path=file_path,
            document_id=document_id,
            original_filename=filename,
            file_type=file_type,
        )
        save_extracted_document(extracted, extracted_dir)
        return extracted

    @staticmethod
    def get_extracted(document_id: str, extracted_dir: Path) -> dict[str, Any] | None:
        return load_extracted_document(document_id, extracted_dir)

