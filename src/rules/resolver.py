"""Conflict resolution between triggered rules.

1. Smaller priority value wins.
2. Same priority: higher severity wins.
3. Same priority and severity: block > review > allow.
4. An allow rule may only override REVIEW decisions of rules with a LOWER priority:
   - any triggered block rule beats allow (whatever its priority);
   - a review rule with the same or a higher priority beats allow;
   - a score-threshold review (no rule decided) is never overridden by allow; this last case
     depends on the score and is applied in RuleEngine.decide (ALLOW_VS_SCORE_REASON).

Rules whose decision equals the final decision are applied (their boosts add up, clipped);
the others are suppressed and the reason is recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from src.rules.schema import DECISION_RANK, SEVERITY_RANK, Rule


@dataclass(frozen=True)
class Resolution:
    """Outcome of conflict resolution for one set of triggered rules."""

    decision: str | None  # None: no rule decided (score-based fallback applies)
    winner: str | None
    applied: tuple[str, ...] = ()
    suppressed: tuple[tuple[str, str], ...] = ()  # (rule id, reason)
    boost_raw: float = 0.0
    boost: float = 0.0
    triggered: tuple[str, ...] = field(default=())


def sort_key(rule: Rule) -> tuple[int, int, int, str]:
    """Order of strength: priority asc, severity desc, decision desc, id."""
    return (
        rule.priority,
        -SEVERITY_RANK[rule.severity],
        -DECISION_RANK[rule.action.decision],
        rule.id,
    )


ALLOW_VS_SCORE_REASON = "allow kuralı, skor eşiğinden gelen review kararını bastıramaz"


def _pick_winner(ordered: list[Rule]) -> Rule:
    risk = [r for r in ordered if r.action.decision != "allow"]
    allows = [r for r in ordered if r.action.decision == "allow"]
    has_block = any(r.action.decision == "block" for r in risk)
    if allows and not has_block and (not risk or allows[0].priority < risk[0].priority):
        return allows[0]
    return risk[0]


def _reason(rule: Rule, winner: Rule, has_block: bool) -> str:
    # allow loses either to the block decision itself, to a block that voids it while a
    # higher-priority review wins, or to a review with the same or higher priority
    """Turkish explanation of why `rule` lost against `winner`."""
    head = (
        f"{winner.id} kazandı (öncelik {winner.priority}, {winner.severity}, "
        f"{winner.action.decision})"
    )
    if rule.action.decision == "allow" and winner.action.decision == "block":
        why = "allow kuralı block kararını hiçbir zaman bastıramaz"
    elif rule.action.decision == "allow" and has_block and rule.priority < winner.priority:
        why = (
            "tetiklenen bir block kuralı allow'u geçersiz kılar; kalan en güçlü kural "
            f"{winner.id} kazandı"
        )
    elif rule.action.decision == "allow":
        why = "allow kuralı, eşit veya daha yüksek öncelikli bir review varken uygulanmaz"
    elif rule.priority > winner.priority:
        why = f"daha yüksek öncelik ({winner.priority} < {rule.priority})"
    elif SEVERITY_RANK[rule.severity] < SEVERITY_RANK[winner.severity]:
        why = f"aynı öncelik, daha yüksek önem ({winner.severity} > {rule.severity})"
    else:
        why = (
            f"aynı öncelik ve önem, karar sırası block > review > allow "
            f"({winner.action.decision} > {rule.action.decision})"
        )
    return f"{head}: {why}"


def resolve(triggered: list[Rule], boost_min: float, boost_max: float) -> Resolution:
    """Resolve the triggered rules of one record into a decision and a clipped boost."""
    if not triggered:
        return Resolution(decision=None, winner=None)
    ordered = sorted(triggered, key=sort_key)
    winner = _pick_winner(ordered)
    decision = winner.action.decision
    applied = [r for r in ordered if r.action.decision == decision]
    has_block = any(r.action.decision == "block" for r in ordered)
    suppressed = [
        (r.id, _reason(r, winner, has_block)) for r in ordered if r.action.decision != decision
    ]
    boost_raw = float(sum(r.action.risk_boost for r in applied))
    return Resolution(
        decision=decision,
        winner=winner.id,
        applied=tuple(r.id for r in applied),
        suppressed=tuple(suppressed),
        boost_raw=boost_raw,
        boost=min(max(boost_raw, boost_min), boost_max),
        triggered=tuple(r.id for r in ordered),
    )


def resolve_score_over_allow(
    triggered: list[Rule], boost_min: float, boost_max: float
) -> Resolution:
    """Resolution when the score reaches the review threshold: allow rules are void (rule 4).

    The remaining rules are resolved as if no allow rule had fired (their reviews and boosts
    apply); the allow rules are listed as suppressed with ALLOW_VS_SCORE_REASON. When no
    block/review rule remains, decision is None and the caller applies the score review.
    """
    allows = sorted((r for r in triggered if r.action.decision == "allow"), key=sort_key)
    rest = resolve([r for r in triggered if r.action.decision != "allow"], boost_min, boost_max)
    return replace(
        rest,
        suppressed=(*rest.suppressed, *[(r.id, ALLOW_VS_SCORE_REASON) for r in allows]),
        triggered=tuple(r.id for r in sorted(triggered, key=sort_key)),
    )
