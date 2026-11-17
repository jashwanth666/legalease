"""Repeatable evaluation suite measuring extraction accuracy, risk detection, and evidence grounding."""

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

from backend.config import Settings, get_settings
from backend.database.db import configure_database
from backend.main import create_app


SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample_contracts"
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "evaluation" / "eval_manifest.json"


class _EvalTestSettings(Settings):
    test_root: Path

    @property
    def upload_dir(self) -> Path:
        return self.test_root / "uploads"

    @property
    def extracted_dir(self) -> Path:
        return self.test_root / "extracted"

    @property
    def vectorstore_dir(self) -> Path:
        return self.test_root / "vectorstore"

    @property
    def reports_dir(self) -> Path:
        return self.test_root / "reports"


@pytest.fixture()
def eval_client(tmp_path: Path):
    db_path = tmp_path / "eval_legalease.db"
    test_settings = _EvalTestSettings(
        test_root=tmp_path,
        database_url=f"sqlite:///{db_path.as_posix()}",
        gemini_api_key="",  # Enforce deterministic fallback for consistent evaluation
    )
    test_settings.ensure_directories()
    configure_database(test_settings.database_url)

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: test_settings

    with TestClient(app) as client:
        yield client, test_settings

    app.dependency_overrides.clear()


def test_eval_manifest_validity():
    """Verify evaluation manifest exists and conforms to schema."""
    assert MANIFEST_PATH.exists(), f"Evaluation manifest missing at {MANIFEST_PATH}"
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest.get("version") == "1.0"
    assert len(manifest.get("contracts", [])) >= 2


def test_nda_extraction_accuracy(eval_client):
    """Measure extraction accuracy against sample_nda.pdf in deterministic fallback mode."""
    client, _ = eval_client
    pdf_path = SAMPLE_DIR / "sample_nda.pdf"
    assert pdf_path.exists()

    with pdf_path.open("rb") as f:
        up = client.post("/api/upload", files={"file": ("sample_nda.pdf", f, "application/pdf")})
    assert up.status_code in (200, 201)
    doc_id = up.json()["document_id"]

    an = client.post(f"/api/analyze/{doc_id}")
    assert an.status_code == 200
    payload = an.json()

    clauses_resp = client.get(f"/api/clauses/{doc_id}")
    assert clauses_resp.status_code == 200
    clauses = clauses_resp.json().get("clauses", [])

    # Extraction assertions
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    nda_spec = next(c for c in manifest["contracts"] if c["filename"] == "sample_nda.pdf")

    assert payload.get("page_count") == nda_spec["expected_page_count"]
    assert len(clauses) >= nda_spec["expected_min_clauses"]
    assert "nda" in (payload.get("detected_contract_type") or "").lower()

    # Calculate category extraction accuracy
    found_categories = {c.get("category") for c in clauses}
    expected_categories = set(nda_spec["expected_categories"])
    matched = found_categories.intersection(expected_categories)
    accuracy_ratio = len(matched) / len(expected_categories)

    print(f"\n[EVAL] NDA Clause Extraction Accuracy: {accuracy_ratio:.1%} ({len(matched)}/{len(expected_categories)} matched)")
    assert accuracy_ratio >= 0.50, f"Extraction accuracy {accuracy_ratio:.2f} is below 50% baseline threshold"


def test_nda_risk_findings_have_evidence(eval_client):
    """Verify that all High and Critical risk findings in sample NDA have verbatim supporting evidence."""
    client, _ = eval_client
    pdf_path = SAMPLE_DIR / "sample_nda.pdf"

    with pdf_path.open("rb") as f:
        up = client.post("/api/upload", files={"file": ("sample_nda.pdf", f, "application/pdf")})
    doc_id = up.json()["document_id"]
    an = client.post(f"/api/analyze/{doc_id}")
    assert an.status_code == 200
    findings = an.json().get("risk_findings", [])

    high_or_crit = [f for f in findings if f.get("risk_level") in {"high", "critical"}]
    for finding in high_or_crit:
        # 1. Verbatim clause text must be present
        clause_text = finding.get("original_clause", "")
        assert bool(clause_text.strip()), f"Finding {finding.get('clause_id')} has no evidence text"

        # 2. Explanation must be non-empty
        explanation = finding.get("explanation", "")
        assert bool(explanation.strip()), f"Finding {finding.get('clause_id')} has no explanation"

        # 3. Location reference must be present
        assert finding.get("page_number") is not None or finding.get("paragraph_index") is not None


def test_service_agreement_known_risks_detected(eval_client):
    """Verify that the Service Agreement analysis flags known risk patterns (e.g. liability caps, indemnities)."""
    client, _ = eval_client
    pdf_path = SAMPLE_DIR / "sample_service_agreement.pdf"
    assert pdf_path.exists()

    with pdf_path.open("rb") as f:
        up = client.post("/api/upload", files={"file": ("sample_service_agreement.pdf", f, "application/pdf")})
    assert up.status_code in (200, 201)
    doc_id = up.json()["document_id"]

    an = client.post(f"/api/analyze/{doc_id}")
    assert an.status_code == 200
    payload = an.json()

    findings = payload.get("risk_findings", [])
    assert len(findings) > 0

    # Check overall risk score is computed
    overall_score = payload.get("overall_risk_score", 0.0)
    assert overall_score > 0.0, "Service Agreement overall risk score must be > 0"

    # Known risk keyword presence
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    msa_spec = next(c for c in manifest["contracts"] if c["filename"] == "sample_service_agreement.pdf")
    expected_keywords = msa_spec["known_risk_keywords"]

    all_finding_text = " ".join(
        f"{f.get('explanation', '')} {f.get('original_clause', '')} {f.get('risk_title', '')}"
        for f in findings
    ).lower()

    detected_keywords = [kw for kw in expected_keywords if kw in all_finding_text]
    print(f"\n[EVAL] Service Agreement Detected Risk Keywords: {detected_keywords} / {expected_keywords}")
    assert len(detected_keywords) >= 2, f"Expected at least 2 risk keywords, found {detected_keywords}"

    # Confirm presence of elevated risk levels
    levels = {f.get("risk_level") for f in findings}
    assert any(lvl in {"high", "critical", "medium"} for lvl in levels)


def test_false_positive_rate(eval_client):
    """Assert false positive bounds: standard bilateral NDA must not produce excessive critical findings."""
    client, _ = eval_client
    pdf_path = SAMPLE_DIR / "sample_nda.pdf"

    with pdf_path.open("rb") as f:
        up = client.post("/api/upload", files={"file": ("sample_nda.pdf", f, "application/pdf")})
    doc_id = up.json()["document_id"]
    an = client.post(f"/api/analyze/{doc_id}")
    assert an.status_code == 200
    findings = an.json().get("risk_findings", [])

    critical_findings = [f for f in findings if f.get("risk_level") == "critical"]
    print(f"\n[EVAL] NDA Critical Findings Count: {len(critical_findings)} (Allowed max: 2)")
    assert len(critical_findings) <= 2, f"Too many critical findings ({len(critical_findings)}) in standard bilateral NDA"
    assert len(findings) <= 15, f"Unreasonable number of total findings ({len(findings)})"


def test_deterministic_vs_gemini_label_accuracy(eval_client):
    """Verify that offline runs are transparently labeled as deterministic fallback, not AI-generated."""
    client, _ = eval_client
    pdf_path = SAMPLE_DIR / "sample_nda.pdf"

    with pdf_path.open("rb") as f:
        up = client.post("/api/upload", files={"file": ("sample_nda.pdf", f, "application/pdf")})
    doc_id = up.json()["document_id"]
    an = client.post(f"/api/analyze/{doc_id}")
    assert an.status_code == 200
    payload = an.json()

    assert payload.get("analysis_mode") == "deterministic_fallback"
    assert payload.get("fallback_used") is True
    assert payload.get("gemini_status") in {"missing_key", "rate_limited", "invalid_credentials", "api_error"}


def test_evidence_verification_accuracy(eval_client):
    """Verify that at least 50% of scored findings have verified evidentiary grounding."""
    client, _ = eval_client
    pdf_path = SAMPLE_DIR / "sample_nda.pdf"

    with pdf_path.open("rb") as f:
        up = client.post("/api/upload", files={"file": ("sample_nda.pdf", f, "application/pdf")})
    doc_id = up.json()["document_id"]
    an = client.post(f"/api/analyze/{doc_id}")
    assert an.status_code == 200
    findings = an.json().get("risk_findings", [])

    scored_findings = [f for f in findings if f.get("risk_level") != "no_notable_risk"]
    if scored_findings:
        verified_count = sum(1 for f in scored_findings if f.get("verified", False))
        grounding_ratio = verified_count / len(scored_findings)
        print(f"\n[EVAL] Evidence Grounding Ratio: {grounding_ratio:.1%} ({verified_count}/{len(scored_findings)} verified)")
        assert grounding_ratio >= 0.50, f"Evidence grounding ratio {grounding_ratio:.2f} is below 50%"


def test_missing_clause_detection_accuracy(eval_client):
    """Verify that standard checklist coverage auditing is executed for NDA and Service Agreement."""
    client, _ = eval_client
    pdf_path = SAMPLE_DIR / "sample_nda.pdf"

    with pdf_path.open("rb") as f:
        up = client.post("/api/upload", files={"file": ("sample_nda.pdf", f, "application/pdf")})
    doc_id = up.json()["document_id"]
    an = client.post(f"/api/analyze/{doc_id}")
    assert an.status_code == 200
    missing = an.json().get("missing_clauses", {})

    assert len(missing.get("checklist_categories", [])) >= 3
    assert len(missing.get("detected_categories", [])) >= 1
