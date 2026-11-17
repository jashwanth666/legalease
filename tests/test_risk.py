"""Tests for Python risk scoring and clause risk assessment."""

from backend.agents.risk_agent import RiskAgent
from backend.schemas.clause import ClauseClassification, ExtractedClause
from backend.schemas.risk import (
    GeminiBatchRiskAssessment,
    GeminiSingleRiskAssessment,
    RiskFactorInputs,
)
from backend.services.llm_service import LLMService
from backend.services.scoring_service import (
    calculate_clause_risk_score,
    calculate_overall_risk_overview,
    classify_risk_level,
)


def test_python_weighted_risk_scoring_boundaries():
    assert classify_risk_level(0) == "low"
    assert classify_risk_level(29) == "low"
    assert classify_risk_level(30) == "medium"
    assert classify_risk_level(59) == "medium"
    assert classify_risk_level(60) == "high"
    assert classify_risk_level(79) == "high"
    assert classify_risk_level(80) == "critical"
    assert classify_risk_level(100) == "critical"

    # 80*0.4 + 70*0.3 + 60*0.2 + 50*0.1 = 32 + 21 + 12 + 5 = 70.0 -> high
    score, level, breakdown = calculate_clause_risk_score(
        RiskFactorInputs(
            severity=80,
            unfavorable_wording=70,
            missing_protections=60,
            ambiguity=50,
        )
    )
    assert score == 70.0
    assert level == "high"
    assert breakdown["weighted_score"] == 70.0


def test_deterministic_risk_assessment_flags_critical_and_high_risks():
    clauses = [
        ExtractedClause(
            clause_id="CL-001",
            title="5. Limitation of Liability",
            category="Liability",
            original_text=(
                "IN NO EVENT SHALL PROVIDER BE LIABLE FOR INDIRECT DAMAGES AND "
                "PROVIDER'S TOTAL AGGREGATE LIABILITY SHALL NOT EXCEED ONE HUNDRED DOLLARS ($100)."
            ),
            page_number=2,
        ),
        ExtractedClause(
            clause_id="CL-002",
            title="6. Indemnification",
            category="Indemnification",
            original_text=(
                "Client agrees to indemnify and hold harmless Provider from all claims "
                "without any reciprocal indemnification from Provider."
            ),
            page_number=2,
        ),
        ExtractedClause(
            clause_id="CL-003",
            title="9. Force Majeure",
            category="Force Majeure",
            original_text="Neither party shall be liable for delays due to natural disasters.",
            page_number=3,
        ),
    ]
    agent = RiskAgent(llm_service=LLMService(api_key=""))
    findings, mode = agent.assess_clauses(clauses)

    assert mode == "deterministic_fallback"
    assert len(findings) == 3
    assert findings[0].risk_level in {"high", "critical"}
    assert findings[0].risk_score >= 70.0
    assert findings[0].page_number == 2
    assert findings[1].risk_level in {"high", "critical"}
    assert findings[2].finding_type == "no_notable_risk"
    assert findings[2].risk_level == "no_notable_risk"
    assert findings[2].risk_score is None
    assert all(f.analysis_source != "gemini" for f in findings)

    overview = calculate_overall_risk_overview(findings)
    assert overview.total_clauses == 3
    assert overview.scored_clauses_count == 2
    assert overview.overall_risk_score > 0
    assert overview.no_notable_risk_count == 1


def test_mocked_gemini_risk_assessment_uses_python_scoring():
    clause = ExtractedClause(
        clause_id="CL-010",
        title="7. Renewal",
        category="Renewal",
        original_text="Agreement renews automatically unless 90 days notice is given.",
        page_number=3,
    )
    classification = ClauseClassification(
        clause_id="CL-010",
        category="Renewal",
        description="Auto-renewal clause.",
        confidence=0.95,
        classification_source="gemini",
    )

    class _MockLLM(LLMService):
        @property
        def is_available(self) -> bool:
            return True

        def invoke_structured(self, system_prompt, user_prompt, schema, temperature=0.1):
            return GeminiBatchRiskAssessment(
                findings=[
                    GeminiSingleRiskAssessment(
                        clause_id="CL-010",
                        risk_title="Long auto-renewal notice window",
                        factors=RiskFactorInputs(
                            severity=70,
                            unfavorable_wording=60,
                            missing_protections=50,
                            ambiguity=30,
                        ),
                        explanation="Requires 90 days prior notice to stop renewal.",
                        potential_impact="Contract locks in for another year if missed.",
                        suggested_action="Reduce notice window to 30 days.",
                        finding_type="detected_risk",
                    )
                ]
            )

    agent = RiskAgent(llm_service=_MockLLM(api_key="fake-key"))
    findings, mode = agent.assess_clauses([clause], [classification])

    assert mode == "gemini"
    assert len(findings) == 1
    # 70*0.4 + 60*0.3 + 50*0.2 + 30*0.1 = 28 + 18 + 10 + 3 = 59.0 -> medium
    assert findings[0].risk_score == 59.0
    assert findings[0].risk_level == "medium"
    assert findings[0].analysis_source == "gemini"


def test_rag_faiss_retrieval_and_template_comparison(tmp_path):
    from pathlib import Path
    from backend.agents.comparison_agent import ComparisonAgent
    from backend.retrieval.embeddings import EmbeddingService
    from backend.retrieval.retriever import TemplateRetriever

    templates_dir = Path(__file__).resolve().parent.parent / "data" / "reference_templates"
    retriever = TemplateRetriever(
        vectorstore_dir=tmp_path / "vectorstore",
        templates_dir=templates_dir,
        embedding_service=EmbeddingService(allow_download=False),
    )
    count = retriever.rebuild()
    assert count >= 30

    clauses = [
        ExtractedClause(
            clause_id="CL-005",
            title="5. Limitation of Liability",
            category="Liability",
            original_text=(
                "IN NO EVENT SHALL PROVIDER BE LIABLE FOR INDIRECT DAMAGES AND "
                "PROVIDER'S TOTAL AGGREGATE LIABILITY SHALL NOT EXCEED ONE HUNDRED DOLLARS ($100)."
            ),
            page_number=2,
        )
    ]

    agent = ComparisonAgent(retriever=retriever, llm_service=LLMService(api_key=""))
    comparisons, retrieved_map, mode = agent.compare_clauses(
        clauses=clauses,
        contract_type="Service Agreement",
    )

    assert mode == "deterministic_fallback"
    assert "CL-005" in retrieved_map
    assert len(retrieved_map["CL-005"]) >= 1
    assert len(comparisons) == 1
    comp = comparisons[0]
    assert comp.reference_source == "service_reference.txt"
    assert "12 months" in comp.differences[0]
    assert "illustrative" in comp.illustrative_notice.lower()


def test_gemini_error_classification_and_fallback_tracking():
    clause = ExtractedClause(
        clause_id="CL-001",
        title="5. Liability",
        category="Liability",
        original_text="Total liability shall not exceed $100.",
        page_number=1,
    )

    class _RateLimitLLM(LLMService):
        @property
        def is_available(self) -> bool:
            return True

        def invoke_structured(self, system_prompt, user_prompt, schema, temperature=0.1):
            raise RuntimeError("429 ResourceExhausted: API rate limit exceeded")

    agent = RiskAgent(llm_service=_RateLimitLLM(api_key="fake-key"))
    findings, mode = agent.assess_clauses([clause])
    assert mode == "deterministic_fallback"
    assert agent.last_run_meta["gemini_status"] == "rate_limited"
    assert agent.last_run_meta["fallback_used"] is True
    assert "rate limit" in str(agent.last_run_meta["fallback_reason"]).lower()
    assert findings[0].gemini_status == "rate_limited"


def test_faiss_rebuilds_when_templates_change(tmp_path):
    from shutil import copytree
    from backend.retrieval.embeddings import EmbeddingService
    from backend.retrieval.vectorstore import ReferenceVectorStore

    src_templates = tmp_path / "templates"
    nda_dir = src_templates / "nda"
    nda_dir.mkdir(parents=True)
    tmpl_file = nda_dir / "nda_reference.txt"
    tmpl_file.write_text(
        "1. Confidentiality\n\nReceiving Party shall protect confidential information.",
        encoding="utf-8",
    )

    store = ReferenceVectorStore(
        vectorstore_dir=tmp_path / "vs",
        templates_dir=src_templates,
        embedding_service=EmbeddingService(allow_download=False),
    )
    count_before = store.build_index()
    assert count_before == 1
    hash_before = store.metadata["template_hash"]
    assert store.metadata["is_semantic_embeddings"] is False
    assert store.metadata["embedding_dimension"] == 384

    # Modify reference templates and reload cleanly
    tmpl_file.write_text(
        "1. Confidentiality\n\nReceiving Party shall protect confidential information.\n\n"
        "2. Termination\n\nEither party may terminate on 30 days notice.",
        encoding="utf-8",
    )
    store2 = ReferenceVectorStore(
        vectorstore_dir=tmp_path / "vs",
        templates_dir=src_templates,
        embedding_service=EmbeddingService(allow_download=False),
    )
    store2.ensure_loaded()
    assert len(store2.records) == 2
    assert store2.metadata["template_hash"] != hash_before


def test_low_quality_rag_retrieval_marked_insufficient_evidence(tmp_path):
    from pathlib import Path
    from backend.agents.comparison_agent import ComparisonAgent
    from backend.retrieval.embeddings import EmbeddingService
    from backend.retrieval.retriever import TemplateRetriever

    templates_dir = Path(__file__).resolve().parent.parent / "data" / "reference_templates"
    retriever = TemplateRetriever(
        vectorstore_dir=tmp_path / "vs_low",
        templates_dir=templates_dir,
        embedding_service=EmbeddingService(allow_download=False),
    )
    retriever.rebuild()

    agent = ComparisonAgent(retriever=retriever, llm_service=LLMService(api_key=""))
    comps, _, _ = agent.compare_clauses(
        [
            ExtractedClause(
                clause_id="CL-UNREL",
                title="Unknown Addendum",
                category="Other",
                original_text="zzzzzz xxxxx qqqqqq completely unrelated gibberish text",
                page_number=1,
            )
        ]
    )
    assert len(comps) == 1
    assert comps[0].insufficient_evidence is True
    assert comps[0].verified is False
    assert "insufficient evidence" in comps[0].differences[0].lower()

