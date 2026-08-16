"""
PARIKA Configuration Merger

Responsible for recursively merging multiple configuration layers
into a single configuration dictionary.

Merge precedence is determined by the order in which layers are
provided. Later layers override earlier layers.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class Merger:
    """
    Deep configuration merger.

    Merge rules:

    - Dictionaries are merged recursively.
    - Scalar values replace previous values.
    - Lists are replaced.
    - Tuples are replaced.
    - Sets are replaced.
    - None is considered a valid overriding value.
    """

    def merge_layers(
        self,
        *layers: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Merge multiple configuration layers.

        Parameters
        ----------
        *layers:
            Configuration dictionaries ordered from
            lowest precedence to highest precedence.

        Returns
        -------
        dict[str, Any]
            The merged configuration.
        """

        merged: dict[str, Any] = {}

        for layer in layers:
            merged = self._merge_dicts(merged, layer)

        return merged

    def _merge_dicts(
        self,
        base: dict[str, Any],
        override: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Recursively merge two dictionaries.
        """

        result = deepcopy(base)

        for key, value in override.items():

            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._merge_dicts(
                    result[key],
                    value,
                )
            else:
                result[key] = deepcopy(value)

        return result