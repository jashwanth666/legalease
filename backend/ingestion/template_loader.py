"""Loader for illustrative reference contract templates in data/reference_templates."""

from dataclasses import dataclass
from pathlib import Path

from backend.ingestion.clause_splitter import split_pages_into_clauses
from backend.ingestion.document_loader import extract_document_text


ILLUSTRATIVE_DEFAULT_NOTICE = (
    "Illustrative reference example only, not a universally applicable legal standard."
)

FOLDER_TO_CONTRACT_TYPE = {
    "nda": "NDA",
    "service_agreement": "Service Agreement",
    "employment": "Employment Agreement",
    "partnership": "Partnership Agreement",
}


@dataclass(frozen=True)
class ReferenceClause:
    """Single reference clause extracted from a reference template."""

    reference_id: str
    contract_type: str
    category: str
    title: str
    text: str
    reference_source: str
    jurisdiction: str
    illustrative_notice: str


def _parse_text_template(file_path: Path, folder_name: str) -> tuple[dict[str, str], str]:
    raw = file_path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    metadata = {
        "contract_type": FOLDER_TO_CONTRACT_TYPE.get(folder_name, folder_name.title()),
        "source": file_path.name,
        "jurisdiction": "General Commercial (Illustrative)",
        "illustrative_notice": ILLUSTRATIVE_DEFAULT_NOTICE,
    }

    body_start = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            body_start = idx + 1
            break
        if ":" in stripped and idx < 8:
            key, val = stripped.split(":", 1)
            k_norm = key.strip().lower().replace(" ", "_")
            if k_norm in metadata:
                metadata[k_norm] = val.strip()
                body_start = idx + 1
        else:
            break

    body = "\n".join(lines[body_start:]).strip()
    return metadata, body


def load_reference_clauses(templates_dir: Path) -> list[ReferenceClause]:
    """Load and split all reference contract templates into structured ReferenceClauses."""
    if not templates_dir.exists():
        return []

    clauses: list[ReferenceClause] = []
    counter = 1

    for folder in sorted(p for p in templates_dir.iterdir() if p.is_dir()):
        folder_name = folder.name
        for file_path in sorted(folder.iterdir()):
            if not file_path.is_file():
                continue
            ext = file_path.suffix.lower()
            if ext not in {".txt", ".md", ".pdf", ".docx"}:
                continue

            if ext in {".txt", ".md"}:
                meta, body = _parse_text_template(file_path, folder_name)
                pages = [{"page_number": 1, "text": body, "headings": []}]
            else:
                meta = {
                    "contract_type": FOLDER_TO_CONTRACT_TYPE.get(folder_name, folder_name.title()),
                    "source": file_path.name,
                    "jurisdiction": "General Commercial (Illustrative)",
                    "illustrative_notice": ILLUSTRATIVE_DEFAULT_NOTICE,
                }
                extracted = extract_document_text(
                    file_path=file_path,
                    document_id=f"REF-{counter:03d}",
                    original_filename=file_path.name,
                    file_type=ext.lstrip("."),
                )
                pages = extracted["pages"]

            split_clauses = split_pages_into_clauses(pages)
            for sc in split_clauses:
                clauses.append(
                    ReferenceClause(
                        reference_id=f"REF-{counter:04d}",
                        contract_type=meta["contract_type"],
                        category=sc.category,
                        title=sc.title,
                        text=sc.original_text,
                        reference_source=meta["source"],
                        jurisdiction=meta["jurisdiction"],
                        illustrative_notice=meta["illustrative_notice"],
                    )
                )
                counter += 1

    return clauses

