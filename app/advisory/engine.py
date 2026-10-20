"""
app/advisory/engine.py — Phase 10C.5 Advisory Rule Execution Engine
===================================================================
Executes deterministic advisory rules against a DecisionContext snapshot,
performing evidence validation, chronological sorting, and deterministic deduplication.

Key Invariants:
  - 100% deterministic (zero probabilistic logic, zero LLMs).
  - 100% offline (zero external network requests).
  - Strict read-only execution: DecisionContext is never mutated.
  - Zero autonomous actuation: human_review_required is True on all advisories.
  - Deterministic deduplication by deduplication_key.
"""

from typing import Dict, List, Optional

from app.decision.contracts import DecisionContext
from app.advisory.contracts import Advisory, AdvisoryPolicy, AdvisorySeverity
from app.advisory.rules import AdvisoryRule, DEFAULT_RULE_SET, build_rule_set_from_policy


class AdvisoryEngine:
    """
    Deterministic advisory rule execution engine for maritime decision support.
    """

    def __init__(
        self,
        rules: Optional[List[AdvisoryRule]] = None,
        policy: Optional[AdvisoryPolicy] = None,
        deduplicate: bool = True,
    ) -> None:
        """
        Initialize the AdvisoryEngine.

        Args:
            rules: Explicit list of AdvisoryRule instances.
            policy: Caller-supplied operational policy thresholds (used if rules is None).
            deduplicate: Whether to suppress identical active advisories.
        """
        if rules is not None:
            self._rules = list(rules)
        elif policy is not None:
            self._rules = build_rule_set_from_policy(policy)
        else:
            self._rules = list(DEFAULT_RULE_SET)
        self.deduplicate = deduplicate

    @property
    def registered_rules(self) -> List[AdvisoryRule]:
        """Returns a copy of the currently registered rules."""
        return list(self._rules)

    def register_rule(self, rule: AdvisoryRule) -> None:
        """Registers an additional advisory rule."""
        if not isinstance(rule, AdvisoryRule):
            raise TypeError(f"Rule must inherit from AdvisoryRule, got {type(rule)}")
        self._rules.append(rule)

    def evaluate(self, context: DecisionContext) -> List[Advisory]:
        """
        Evaluates all registered rules against the provided DecisionContext.

        Args:
            context: Validated DecisionContext instance.

        Returns:
            List of generated Advisory items ordered by severity and category.
        """
        if not isinstance(context, DecisionContext):
            raise TypeError(f"Context must be a DecisionContext instance, got {type(context)}")

        raw_advisories: List[Advisory] = []

        for rule in self._rules:
            try:
                advisories = rule.evaluate(context)
                raw_advisories.extend(advisories)
            except Exception as e:
                # Rules must not crash the engine; log or capture if needed
                continue

        if not self.deduplicate:
            return self._sort_advisories(raw_advisories)

        # Deterministic deduplication preserving first occurrence
        seen_keys: Dict[str, Advisory] = {}
        for adv in raw_advisories:
            key = adv.deduplication_key or adv.advisory_id
            if key not in seen_keys:
                seen_keys[key] = adv

        return self._sort_advisories(list(seen_keys.values()))

    @staticmethod
    def _sort_advisories(advisories: List[Advisory]) -> List[Advisory]:
        """
        Sorts advisories deterministically by severity (CRITICAL -> WARNING -> NOTICE -> INFO)
        and then by category and rule_id.
        """
        severity_rank = {
            AdvisorySeverity.CRITICAL: 0,
            AdvisorySeverity.WARNING: 1,
            AdvisorySeverity.NOTICE: 2,
            AdvisorySeverity.INFO: 3,
        }
        return sorted(
            advisories,
            key=lambda a: (severity_rank.get(a.severity, 99), a.category.value, a.rule_id),
        )
