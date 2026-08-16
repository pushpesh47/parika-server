"""
Unit tests for `parika.modules.voice.text_chunking`.
"""

from __future__ import annotations

from parika.modules.voice.text_chunking import split_into_speech_chunks


def test_empty_text_produces_no_chunks() -> None:
    assert split_into_speech_chunks("", max_characters=100) == ()
    assert split_into_speech_chunks("   ", max_characters=100) == ()


def test_short_text_produces_one_chunk() -> None:
    chunks = split_into_speech_chunks("Hello there.", max_characters=100)

    assert chunks == ("Hello there.",)


def test_splits_on_sentence_boundaries_when_over_the_limit() -> None:
    text = "Sentence one is here. Sentence two is here. Sentence three is here."

    chunks = split_into_speech_chunks(text, max_characters=30)

    assert chunks == (
        "Sentence one is here.",
        "Sentence two is here.",
        "Sentence three is here.",
    )
    assert all(len(chunk) <= 30 for chunk in chunks)


def test_packs_multiple_short_sentences_into_one_chunk() -> None:
    text = "Hi. Ok. Sure."

    chunks = split_into_speech_chunks(text, max_characters=100)

    assert chunks == ("Hi. Ok. Sure.",)


def test_oversized_single_sentence_is_split_on_word_boundaries() -> None:
    text = "word " * 40  # one long "sentence" with no punctuation

    chunks = split_into_speech_chunks(text, max_characters=20)

    assert len(chunks) > 1
    assert all(len(chunk) <= 20 for chunk in chunks)
    assert " ".join(chunks).replace("  ", " ").strip() == " ".join(text.split())


def test_zero_or_negative_max_characters_returns_one_unsplit_chunk() -> None:
    text = "Sentence one. Sentence two."

    assert split_into_speech_chunks(text, max_characters=0) == (
        "Sentence one. Sentence two.",
    )
    assert split_into_speech_chunks(text, max_characters=-5) == (
        "Sentence one. Sentence two.",
    )


def test_normalizes_internal_whitespace() -> None:
    chunks = split_into_speech_chunks(
        "Hello   there.\n\nHow  are you?", max_characters=100
    )

    assert chunks == ("Hello there. How are you?",)
