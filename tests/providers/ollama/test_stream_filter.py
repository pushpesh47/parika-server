"""
Unit tests for `ToolMarkupStreamFilter`.
"""

from __future__ import annotations

from parika.providers.ollama.stream_filter import ToolMarkupStreamFilter


class TestOrdinaryText:
    def test_ordinary_fragments_pass_through_immediately(self) -> None:
        filt = ToolMarkupStreamFilter()

        assert filt.feed("Hello") == "Hello"
        assert filt.feed(", world!") == ", world!"
        assert filt.flush() == ""

    def test_empty_fragment_yields_nothing(self) -> None:
        filt = ToolMarkupStreamFilter()

        assert filt.feed("") == ""

    def test_prose_mentioning_function_is_never_withheld(self) -> None:
        filt = ToolMarkupStreamFilter()

        text = "Here is a function that computes the answer:"
        fragments = [word + " " for word in text.split(" ")]
        released = "".join(filt.feed(fragment) for fragment in fragments)
        released += filt.flush()

        assert released == "".join(fragments)


class TestSingleChunkMarkup:
    def test_xml_style_markup_never_reaches_the_sink(self) -> None:
        filt = ToolMarkupStreamFilter()

        released = filt.feed(
            "<function=get_current_datetime>\n"
            "<parameter=timezone>\nIST\n</parameter>\n"
            "</function>\n</tool_call>"
        )

        assert released == ""
        assert filt.flush() == ""

    def test_hermes_style_markup_never_reaches_the_sink(self) -> None:
        filt = ToolMarkupStreamFilter()

        released = filt.feed(
            '<tool_call>{"name": "web_search", "arguments": {}}</tool_call>'
        )

        assert released == ""
        assert filt.flush() == ""

    def test_preamble_before_markup_still_streams_live(self) -> None:
        filt = ToolMarkupStreamFilter()

        released = filt.feed("Sure, let me check that. <function=foo></function>")

        assert released == "Sure, let me check that. "
        assert filt.flush() == ""


class TestMarkupSpanningMultipleChunks:
    def test_hint_split_across_fragments_is_still_suppressed(self) -> None:
        filt = ToolMarkupStreamFilter()

        released = []
        for fragment in ["<func", "tion=get_current_datetime>", "<param", "eter=timezone>IST</parameter></function>"]:
            released.append(filt.feed(fragment))

        assert "".join(released) == ""
        assert filt.flush() == ""

    def test_prefix_never_completes_is_flushed_at_end(self) -> None:
        filt = ToolMarkupStreamFilter()

        released = []
        released.append(filt.feed("The value is less than <"))
        released.append(filt.feed(" 5, not a function call."))

        combined = "".join(released) + filt.flush()

        assert combined == "The value is less than < 5, not a function call."

    def test_single_character_prefix_ambiguity_resolves_quickly(self) -> None:
        filt = ToolMarkupStreamFilter()

        # "<" alone is a prefix of both hints, so it is withheld...
        assert filt.feed("<") == ""
        # ...until the next character disambiguates it away from
        # either hint, at which point it (and everything after) is
        # released immediately - no waiting for end of turn.
        assert filt.feed(" 5") == "< 5"

    def test_suppression_persists_once_confirmed_even_across_chunks(self) -> None:
        filt = ToolMarkupStreamFilter()

        assert filt.feed("<tool_call>") == ""
        # Once confirmed, every subsequent fragment this turn is
        # withheld too, even far removed from the markup itself.
        assert filt.feed('{"name": "x"}') == ""
        assert filt.feed("</tool_call>") == ""
        assert filt.feed("trailing prose") == ""
        assert filt.flush() == ""


class TestInstanceIsolation:
    def test_suppression_state_never_leaks_across_instances(self) -> None:
        first = ToolMarkupStreamFilter()
        first.feed("<tool_call>leaked</tool_call>")

        second = ToolMarkupStreamFilter()

        assert second.feed("Hi there!") == "Hi there!"
        assert second.flush() == ""
