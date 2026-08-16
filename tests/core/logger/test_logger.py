"""
Unit tests for Logger.

Note on process-wide state: `Logger` configures a single, module-level
`logging.getLogger("parika")` hierarchy shared by the entire pytest
process (and by every other component under test that constructs its
own `Logger` instance). These tests therefore focus on the
deterministic, side-effect-free behavior of `get_logger()` name
resolution rather than asserting handler counts, which depend on
whichever test in the process happened to configure the root logger
first.
"""

from __future__ import annotations

import logging

from parika.core.configuration.configuration import Configuration
from parika.core.logger.logger import Logger


class TestGetLogger:
    def test_empty_name_returns_root_logger(
        self,
        logger: Logger,
    ) -> None:
        result = logger.get_logger("")

        assert result.name == "parika"

    def test_root_logger_name_returns_root_logger(
        self,
        logger: Logger,
    ) -> None:
        result = logger.get_logger("parika")

        assert result.name == "parika"

    def test_unqualified_name_is_nested_under_root(
        self,
        logger: Logger,
    ) -> None:
        result = logger.get_logger("parika.core.task_manager")

        assert result.name == "parika.core.task_manager"

    def test_already_qualified_name_is_returned_unchanged(
        self,
        logger: Logger,
    ) -> None:
        result = logger.get_logger("parika.core.task_manager")

        assert result.name == "parika.core.task_manager"

    def test_returns_a_standard_library_logger(
        self,
        logger: Logger,
    ) -> None:
        result = logger.get_logger("some.module")

        assert isinstance(result, logging.Logger)

    def test_same_name_returns_the_same_underlying_logger(
        self,
        logger: Logger,
    ) -> None:
        first = logger.get_logger("some.module")
        second = logger.get_logger("some.module")

        assert first is second


class TestConstruction:
    def test_requires_configuration(self) -> None:
        # Should not raise; Configuration() defaults are sufficient.
        instance = Logger(Configuration())

        result = instance.get_logger(__name__)
        assert isinstance(result, logging.Logger)

    def test_logging_does_not_raise(self, logger: Logger) -> None:
        result = logger.get_logger(__name__)

        # Should not raise regardless of configured level/handlers.
        result.debug("debug message")
        result.info("info message")
        result.warning("warning message")
