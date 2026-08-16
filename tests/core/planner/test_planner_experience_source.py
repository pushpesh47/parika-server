"""
Unit tests for Planner's `experience_source` wiring (see
docs/architecture/Intelligence_Foundation_Design.md section 6A).

`_default_scoring_rules()` is a small private helper; testing it
directly is the most precise way to verify the rebuild logic without
duplicating the full Planner construction fixture set.
"""

from __future__ import annotations

from parika.core.planner.model_selection import DEFAULT_SCORING_RULES, ExperienceRule
from parika.core.planner.planner import _default_scoring_rules


class _FakeExperienceSource:
    def aggregate_outcome_rate(
        self, *, capability_id: str, provider_id: str | None = None, model_id: str | None = None
    ) -> float | None:
        return 1.0


class TestDefaultScoringRules:
    def test_returns_unchanged_default_when_no_source(self) -> None:
        assert _default_scoring_rules(None) is DEFAULT_SCORING_RULES

    def test_rebuilds_experience_rule_with_source_when_given(self) -> None:
        source = _FakeExperienceSource()

        rules = _default_scoring_rules(source)

        assert len(rules) == len(DEFAULT_SCORING_RULES)

        experience_rules = [rule for rule in rules if isinstance(rule, ExperienceRule)]
        assert len(experience_rules) == 1
        assert experience_rules[0]._experience_source is source

    def test_every_other_rule_is_unchanged(self) -> None:
        source = _FakeExperienceSource()

        rules = _default_scoring_rules(source)

        for original, rebuilt in zip(DEFAULT_SCORING_RULES, rules, strict=True):
            if isinstance(original, ExperienceRule):
                continue
            assert original is rebuilt
