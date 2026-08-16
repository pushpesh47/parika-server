"""
Unit tests for `parika.interfaces.commands.registry.CommandRegistry`.
"""

from __future__ import annotations

import pytest

from parika.interfaces.commands.base import CommandResult, CommandSpec
from parika.interfaces.commands.registry import CommandRegistry
from parika.interfaces.errors import UnknownCommandError


class TestIsCommand:
    def test_recognizes_leading_slash(self) -> None:
        registry = CommandRegistry()

        assert registry.is_command("/help")
        assert registry.is_command("  /help  ")
        assert not registry.is_command("help")
        assert not registry.is_command("hello /help")


class TestRegister:
    def test_rejects_duplicate_names(self) -> None:
        registry = CommandRegistry()
        spec = CommandSpec(
            name="foo", description="d", handler=lambda s, a: CommandResult(text="")
        )

        registry.register(spec)

        with pytest.raises(ValueError):
            registry.register(spec)

    def test_list_specs_is_sorted(self) -> None:
        registry = CommandRegistry()
        registry.register(
            CommandSpec(name="zebra", description="", handler=lambda s, a: CommandResult(text=""))
        )
        registry.register(
            CommandSpec(name="alpha", description="", handler=lambda s, a: CommandResult(text=""))
        )

        names = [spec.name for spec in registry.list_specs()]

        assert names == ["alpha", "zebra"]


class TestDispatch:
    def test_dispatches_to_registered_handler(self) -> None:
        registry = CommandRegistry()
        calls: list[str] = []

        def _handler(session, args):  # noqa: ANN001
            calls.append(args)
            return CommandResult(text=f"got: {args}")

        registry.register(
            CommandSpec(name="echo", description="", handler=_handler)
        )

        result = registry.dispatch("/echo hello world", session=None)  # type: ignore[arg-type]

        assert result.text == "got: hello world"
        assert calls == ["hello world"]

    def test_dispatch_is_case_insensitive(self) -> None:
        registry = CommandRegistry()
        registry.register(
            CommandSpec(
                name="help", description="", handler=lambda s, a: CommandResult(text="ok")
            )
        )

        result = registry.dispatch("/HELP", session=None)  # type: ignore[arg-type]

        assert result.text == "ok"

    def test_unknown_command_raises(self) -> None:
        registry = CommandRegistry()

        with pytest.raises(UnknownCommandError):
            registry.dispatch("/nonexistent", session=None)  # type: ignore[arg-type]

    def test_handler_exception_is_captured_into_result(self) -> None:
        registry = CommandRegistry()

        def _boom(session, args):  # noqa: ANN001
            raise RuntimeError("boom")

        registry.register(
            CommandSpec(name="boom", description="", handler=_boom)
        )

        result = registry.dispatch("/boom", session=None)  # type: ignore[arg-type]

        assert "boom" in result.text
        assert not result.should_exit
