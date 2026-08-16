"""
Unit tests for the Configuration Merger.
"""

from __future__ import annotations

from parika.core.configuration.merger import Merger


class TestMergeLayers:
    def test_no_layers_returns_empty_dict(self) -> None:
        merger = Merger()

        assert merger.merge_layers() == {}

    def test_single_layer_returns_equivalent_dict(self) -> None:
        merger = Merger()

        result = merger.merge_layers({"a": 1, "b": 2})

        assert result == {"a": 1, "b": 2}

    def test_later_layer_overrides_scalar_values(self) -> None:
        merger = Merger()

        result = merger.merge_layers({"a": 1}, {"a": 2})

        assert result == {"a": 2}

    def test_dictionaries_are_merged_recursively(self) -> None:
        merger = Merger()

        result = merger.merge_layers(
            {"logging": {"level": "INFO", "directory": "logs"}},
            {"logging": {"level": "DEBUG"}},
        )

        assert result == {
            "logging": {"level": "DEBUG", "directory": "logs"}
        }

    def test_lists_are_replaced_not_merged(self) -> None:
        merger = Merger()

        result = merger.merge_layers(
            {"tags": ["a", "b"]},
            {"tags": ["c"]},
        )

        assert result == {"tags": ["c"]}

    def test_tuples_are_replaced_not_merged(self) -> None:
        merger = Merger()

        result = merger.merge_layers(
            {"tags": ("a", "b")},
            {"tags": ("c",)},
        )

        assert result == {"tags": ("c",)}

    def test_sets_are_replaced_not_merged(self) -> None:
        merger = Merger()

        result = merger.merge_layers(
            {"tags": {"a", "b"}},
            {"tags": {"c"}},
        )

        assert result == {"tags": {"c"}}

    def test_none_is_a_valid_overriding_value(self) -> None:
        merger = Merger()

        result = merger.merge_layers({"a": 1}, {"a": None})

        assert result == {"a": None}

    def test_new_keys_from_later_layers_are_added(self) -> None:
        merger = Merger()

        result = merger.merge_layers({"a": 1}, {"b": 2})

        assert result == {"a": 1, "b": 2}

    def test_three_layers_merge_in_precedence_order(self) -> None:
        merger = Merger()

        result = merger.merge_layers(
            {"a": 1, "b": 1},
            {"b": 2, "c": 2},
            {"c": 3},
        )

        assert result == {"a": 1, "b": 2, "c": 3}

    def test_result_is_independent_of_input_layers(self) -> None:
        merger = Merger()

        layer_one = {"nested": {"value": 1}}
        result = merger.merge_layers(layer_one, {})

        result["nested"]["value"] = 999

        assert layer_one["nested"]["value"] == 1

    def test_mutating_original_layer_after_merge_does_not_affect_result(
        self,
    ) -> None:
        merger = Merger()

        layer_one = {"nested": {"value": 1}}
        result = merger.merge_layers(layer_one, {})

        layer_one["nested"]["value"] = 999

        assert result["nested"]["value"] == 1
