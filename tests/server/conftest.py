"""
Shared fixtures for `tests/server/`. Mirrors `tests/api/conftest.py`
(both need the same isolated-runtime-factory convention); kept as a
short, separate file rather than a cross-directory import because
pytest fixtures do not cross sibling `conftest.py` boundaries.
"""

from __future__ import annotations

import pytest

from parika.interfaces.runtime import ParikaRuntime, build_default_runtime


@pytest.fixture
def runtime_factory(tmp_path):
    def _factory() -> ParikaRuntime:
        return build_default_runtime(
            discover_ollama_models=False,
            discover_comfyui_models=False,
            load_modules=True,
            data_directory=tmp_path,
        )

    return _factory
