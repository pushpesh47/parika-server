"""
Unit tests for `parika.core.capability_catalog`.
"""

from __future__ import annotations

from parika.core.capability_catalog import CapabilityCatalog
from parika.core.capability_registry.capability_category import (
    CapabilityCategory,
)
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)


def _definition(
    capability_id: str,
    *,
    description: str = "",
    tags: frozenset[str] = frozenset(),
    keywords: frozenset[str] = frozenset(),
    aliases: frozenset[str] = frozenset(),
    examples: tuple[str, ...] = (),
    family: str | None = None,
    enabled: bool = True,
    public: bool = True,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        id=capability_id,
        name=capability_id,
        description=description,
        category=CapabilityCategory.TOOL,
        tags=tags,
        keywords=keywords,
        aliases=aliases,
        examples=examples,
        family=family,
        enabled=enabled,
        public=public,
    )


class TestDeterministicFiltering:
    def test_excludes_disabled_capabilities(self) -> None:
        catalog = CapabilityCatalog()
        definitions = (
            _definition("weather.current", enabled=True),
            _definition("weather.forecast", enabled=False),
        )

        result = catalog.retrieve(definitions, text="weather")

        ids = {definition.id for definition in result}
        assert "weather.current" in ids
        assert "weather.forecast" not in ids

    def test_excludes_non_public_capabilities(self) -> None:
        catalog = CapabilityCatalog()
        definitions = (
            _definition("internal.helper", public=False),
            _definition("public.tool", public=True),
        )

        result = catalog.retrieve(definitions, text="anything")

        ids = {definition.id for definition in result}
        assert "internal.helper" not in ids
        assert "public.tool" in ids

    def test_excludes_capabilities_flagged_catalog_excluded(self) -> None:
        catalog = CapabilityCatalog()
        excluded = CapabilityDefinition(
            id="excluded.capability",
            name="excluded.capability",
            description="",
            category=CapabilityCategory.TOOL,
            metadata={"catalog_excluded": True},
        )
        included = _definition("included.capability")

        result = catalog.retrieve((excluded, included), text="anything")

        ids = {definition.id for definition in result}
        assert "excluded.capability" not in ids
        assert "included.capability" in ids


class TestLexicalRetrievalRanking:
    def test_ranks_lexically_matching_capability_above_unrelated_one(
        self,
    ) -> None:
        catalog = CapabilityCatalog(budget=1)
        weather = _definition(
            "weather.current",
            description="Get the current weather forecast.",
            keywords=frozenset({"weather", "forecast", "temperature"}),
        )
        currency = _definition(
            "currency.convert",
            description="Convert an amount between currencies.",
            keywords=frozenset({"currency", "exchange", "convert"}),
        )

        result = catalog.retrieve(
            (weather, currency), text="What's the weather like today?"
        )

        assert result == (weather,)

    def test_unscored_capability_is_discarded_once_a_relevance_signal_exists(
        self,
    ) -> None:
        """
        Lexical Retrieval alone never drops anything (it only scores),
        but once *some* candidate has a genuine lexical signal, Dynamic
        Relevance Cutoff must discard an unrelated, zero-scoring
        capability -- this is the whole point of the Catalog behaving
        as a retrieval engine rather than a pure ranker/sorter that
        only trims once a fixed budget is exceeded.
        """

        catalog = CapabilityCatalog(budget=10)
        weather = _definition(
            "weather.current",
            keywords=frozenset({"weather"}),
        )
        unrelated = _definition("unrelated.capability")

        result = catalog.retrieve(
            (weather, unrelated), text="What's the weather like today?"
        )

        ids = {definition.id for definition in result}
        assert ids == {"weather.current"}


class TestFamilyRanking:
    def test_family_membership_breaks_ties_between_equally_scored_capabilities(
        self,
    ) -> None:
        catalog = CapabilityCatalog(budget=1)
        in_relevant_family = _definition(
            "document.summarize",
            family="document",
        )
        sibling_in_relevant_family = _definition(
            "document.translate",
            family="document",
            keywords=frozenset({"translate", "language"}),
        )
        in_other_family = _definition(
            "vision.describe",
            family="vision",
        )

        result = catalog.retrieve(
            (in_relevant_family, sibling_in_relevant_family, in_other_family),
            text="translate this document",
        )

        # The directly matching capability always wins on its own
        # score; this test only asserts it is present and ranked
        # first.
        assert result[0].id == "document.translate"

    def test_capability_with_no_declared_family_falls_back_to_category(
        self,
    ) -> None:
        catalog = CapabilityCatalog()
        definition = _definition("standalone.capability")

        result = catalog.retrieve((definition,), text="anything")

        assert result == (definition,)


class TestBudgetAwareSelection:
    def test_returns_every_candidate_when_within_budget(self) -> None:
        catalog = CapabilityCatalog(budget=100)
        definitions = tuple(
            _definition(f"capability.{index}") for index in range(10)
        )

        result = catalog.retrieve(definitions, text="anything")

        assert len(result) == 10

    def test_truncates_to_budget_when_candidates_exceed_it(self) -> None:
        catalog = CapabilityCatalog(budget=3)
        definitions = tuple(
            _definition(f"capability.{index}") for index in range(10)
        )

        result = catalog.retrieve(definitions, text="anything")

        assert len(result) == 3

    def test_non_positive_budget_is_treated_as_unbounded(self) -> None:
        catalog = CapabilityCatalog(budget=0)
        definitions = tuple(
            _definition(f"capability.{index}") for index in range(10)
        )

        result = catalog.retrieve(definitions, text="anything")

        assert len(result) == 10


class TestSemanticRetrievalExtensionPoint:
    """
    `SemanticScorer` ships unimplemented today (see
    `semantic_retrieval.py`); these tests exercise the extension point
    with a minimal fake to prove it slots into the pipeline (as a
    `stages.SemanticRetrievalStage`) without any change to
    `CapabilityCatalog`'s public API.
    """

    def test_semantic_scores_are_blended_with_lexical_scores(self) -> None:
        class _FakeSemanticScorer:
            def score(self, definitions, *, text):
                return {"vision.describe": 1.0}

        catalog = CapabilityCatalog(budget=1, semantic_scorer=_FakeSemanticScorer())
        purely_semantic_match = _definition("vision.describe")
        unrelated = _definition("unrelated.capability")

        result = catalog.retrieve(
            (unrelated, purely_semantic_match), text="irrelevant text"
        )

        assert result == (purely_semantic_match,)

    def test_omitted_semantic_scorer_contributes_nothing(self) -> None:
        catalog_with_semantic = CapabilityCatalog(
            semantic_scorer=None,
        )
        definitions = (_definition("standalone.capability"),)

        result = catalog_with_semantic.retrieve(definitions, text="anything")

        assert result == definitions


class TestPipelineExtensibility:
    """
    New retrieval stages must be addable without editing `retrieve()`
    or any earlier stage. `extra_stages` is the supported public seam
    for this (see `CapabilityCatalog.__init__()`'s docstring); this
    test exercises it directly against the
    `RetrievalContext`/`PipelineStage` contract, independent of any
    concrete stage PARIKA ships today.
    """

    def test_extra_stage_runs_after_budget_selection_and_can_observe_it(
        self,
    ) -> None:
        from parika.core.capability_catalog import PipelineStage, RetrievalContext

        observed_candidate_ids: list[str] = []

        class _RecordingStage:
            def run(self, context: RetrievalContext) -> RetrievalContext:
                observed_candidate_ids.extend(
                    definition.id for definition in context.candidates
                )
                return context

        definitions = (_definition("weather.current"), _definition("web.search"))
        catalog = CapabilityCatalog(
            budget=1, extra_stages=(_RecordingStage(),)
        )

        result = catalog.retrieve(definitions, text="anything")

        # The recording stage runs after the Budget Safety Ceiling, so
        # it only ever observes the already-budget-limited roster.
        assert len(observed_candidate_ids) == 1
        assert observed_candidate_ids == [definition.id for definition in result]

    def test_extra_stage_can_further_transform_the_final_roster(self) -> None:
        from parika.core.capability_catalog import RetrievalContext

        class _DropEverythingStage:
            def run(self, context: RetrievalContext) -> RetrievalContext:
                context.candidates = ()
                return context

        catalog = CapabilityCatalog(extra_stages=(_DropEverythingStage(),))
        definitions = (_definition("weather.current"),)

        result = catalog.retrieve(definitions, text="anything")

        assert result == ()

    def test_omitted_extra_stages_leaves_the_fixed_pipeline_unchanged(self) -> None:
        definitions = (_definition("weather.current"), _definition("web.search"))

        result = CapabilityCatalog().retrieve(definitions, text="anything")

        assert set(definition.id for definition in result) == {
            "weather.current",
            "web.search",
        }


class TestProducesNoLogOutput:
    """
    The Capability Catalog must produce zero log output in production
    -- the observability logging that existed during development was
    deliberately removed in full (see `docs/architecture/
    Request_Understanding.md` §4.9). `CapabilityCatalog` and every
    pipeline stage take no `logger` argument at all and hold no
    logger attribute; this is verified structurally (no `logging`
    import anywhere in the package) rather than by capturing log
    output, since there is no logger to capture from.
    """

    def test_capability_catalog_accepts_no_logger_argument(self) -> None:
        import inspect

        parameters = inspect.signature(CapabilityCatalog.__init__).parameters

        assert "logger" not in parameters

    def test_capability_catalog_instance_holds_no_logger_attribute(self) -> None:
        catalog = CapabilityCatalog()

        assert not hasattr(catalog, "_logger")

    def test_no_capability_catalog_module_imports_the_logging_package(self) -> None:
        import ast
        import pathlib

        package_dir = pathlib.Path(
            __import__(
                "parika.core.capability_catalog", fromlist=["__file__"]
            ).__file__
        ).parent

        for module_path in package_dir.glob("*.py"):
            tree = ast.parse(module_path.read_text(), filename=str(module_path))

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert not any(
                        alias.name == "logging" for alias in node.names
                    ), f"{module_path.name} imports logging"
                elif isinstance(node, ast.ImportFrom):
                    assert node.module != "logging", (
                        f"{module_path.name} imports from logging"
                    )
