"""Map bounded risk and rule policy signals to an operational decision."""

from typing import Literal, Sequence

from app.rules.engine import RuleMatch

Decision = Literal["approve", "review", "decline"]


def decide(
    risk_score: float,
    review_threshold: float,
    rule_matches: Sequence[RuleMatch | str],
    decline_threshold: float = 1.0,
    *,
    decline_reasons: set[str] | None = None,
) -> tuple[Decision, list[str]]:
    """Apply decline precedence, then review policy, and return unique reason codes."""
    reasons = list(
        dict.fromkeys(match.reason if isinstance(match, RuleMatch) else match for match in rule_matches)
    )
    forced_decline = any(
        match.decision == "decline"
        if isinstance(match, RuleMatch)
        else match in (decline_reasons or set())
        for match in rule_matches
    )
    if forced_decline or risk_score >= decline_threshold:
        if risk_score >= decline_threshold:
            reasons.append("decline_threshold_exceeded")
        return "decline", list(dict.fromkeys(reasons))
    has_review_rule = any(
        match.decision == "review" if isinstance(match, RuleMatch) else bool(match)
        for match in rule_matches
    )
    if risk_score >= review_threshold or has_review_rule:
        if risk_score >= review_threshold:
            reasons.append("review_threshold_exceeded")
        return "review", list(dict.fromkeys(reasons))
    return "approve", reasons
