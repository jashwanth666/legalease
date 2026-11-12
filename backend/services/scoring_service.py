"""Transparent Python risk scoring service for LegalEase."""

from typing import Iterable

from backend.schemas.risk import RiskFactorInputs, RiskFinding, RiskLevel, RiskOverview


WEIGHTS = {
    "severity": 0.40,
    "unfavorable_wording": 0.30,
    "missing_protections": 0.20,
    "ambiguity": 0.10,
}


def clamp_score(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def classify_risk_level(score: float) -> RiskLevel:
    """Map numeric score (0-100) to categorical risk level."""
    rounded = round(clamp_score(score), 1)
    if rounded < 30.0:
        return "low"
    if rounded < 60.0:
        return "medium"
    if rounded < 80.0:
        return "high"
    return "critical"


def calculate_clause_risk_score(factors: RiskFactorInputs) -> tuple[float, RiskLevel, dict[str, float]]:
    """Calculate weighted illustrative risk score purely in Python."""
    s = clamp_score(factors.severity)
    u = clamp_score(factors.unfavorable_wording)
    m = clamp_score(factors.missing_protections)
    a = clamp_score(factors.ambiguity)

    weighted = (
        s * WEIGHTS["severity"]
        + u * WEIGHTS["unfavorable_wording"]
        + m * WEIGHTS["missing_protections"]
        + a * WEIGHTS["ambiguity"]
    )
    score = round(clamp_score(weighted), 1)
    level = classify_risk_level(score)

    breakdown = {
        "severity": round(s, 1),
        "unfavorable_wording": round(u, 1),
        "missing_protections": round(m, 1),
        "ambiguity": round(a, 1),
        "weighted_score": score,
    }
    return score, level, breakdown


def calculate_overall_risk_overview(findings: Iterable[RiskFinding]) -> RiskOverview:
    """Compute contract-level illustrative risk overview separating detected risk from unflagged clauses."""
    items = list(findings)
    if not items:
        return RiskOverview(
            overall_risk_score=0.0,
            overall_risk_level="no_notable_risk",
            total_clauses=0,
        )

    counts = {
        "no_notable_risk": 0,
        "uncertain": 0,
        "low": 0,
        "medium": 0,
        "high": 0,
        "critical": 0,
    }
    detected_scores: list[float] = []

    for item in items:
        if item.finding_type in ("uncertain_finding", "missing_information"):
            counts["uncertain"] += 1
        elif item.finding_type == "no_notable_risk" or item.risk_score is None:
            counts["no_notable_risk"] += 1
        else:
            lvl = item.risk_level if item.risk_level in ("low", "medium", "high", "critical") else classify_risk_level(item.risk_score)
            counts[lvl] += 1
            detected_scores.append(float(item.risk_score))

    if not detected_scores:
        return RiskOverview(
            overall_risk_score=0.0,
            overall_risk_level="no_notable_risk",
            total_clauses=len(items),
            scored_clauses_count=0,
            no_notable_risk_count=counts["no_notable_risk"],
            uncertain_count=counts["uncertain"],
            low_count=counts["low"],
            medium_count=counts["medium"],
            high_count=counts["high"],
            critical_count=counts["critical"],
        )

    # Blend top-3 peak detected risks (55%) with contract-wide flagged risk density across all clauses (45%)
    top_scores = sorted(detected_scores, reverse=True)[: min(3, len(detected_scores))]
    peak_avg = sum(top_scores) / len(top_scores)
    contract_density = sum(detected_scores) / len(items)

    overall = round(clamp_score(0.55 * peak_avg + 0.45 * contract_density), 1)
    overall_level = classify_risk_level(overall)

    return RiskOverview(
        overall_risk_score=overall,
        overall_risk_level=overall_level,
        total_clauses=len(items),
        scored_clauses_count=len(detected_scores),
        no_notable_risk_count=counts["no_notable_risk"],
        uncertain_count=counts["uncertain"],
        low_count=counts["low"],
        medium_count=counts["medium"],
        high_count=counts["high"],
        critical_count=counts["critical"],
    )

