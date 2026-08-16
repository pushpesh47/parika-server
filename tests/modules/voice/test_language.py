"""
Unit tests for `parika.modules.voice.language`.
"""

from __future__ import annotations

import pytest

from parika.modules.voice.language import (
    DEFAULT_FALLBACK_LANGUAGE,
    VoiceInputLanguage,
    VoiceLanguageError,
    VoiceLanguagePreference,
    VoiceLanguagePreferenceStore,
    VoiceOutputLanguage,
    is_supported_spoken_language,
    parse_input_language,
    parse_output_language,
)


class TestParseInputLanguage:
    @pytest.mark.parametrize(
        "value",
        [None, "", "auto", "AUTO", "  auto  "],
    )
    def test_none_empty_and_auto_all_mean_auto(self, value) -> None:
        assert parse_input_language(value) is VoiceInputLanguage.AUTO

    def test_en_and_hi_parse_case_insensitively(self) -> None:
        assert parse_input_language("en") is VoiceInputLanguage.ENGLISH
        assert parse_input_language("HI") is VoiceInputLanguage.HINDI

    def test_unsupported_value_raises(self) -> None:
        with pytest.raises(VoiceLanguageError):
            parse_input_language("fr")


class TestParseOutputLanguage:
    @pytest.mark.parametrize(
        "value",
        [None, "", "follow_input", "FOLLOW_INPUT"],
    )
    def test_none_empty_and_follow_input_all_mean_follow_input(self, value) -> None:
        assert parse_output_language(value) is VoiceOutputLanguage.FOLLOW_INPUT

    def test_en_and_hi_parse_case_insensitively(self) -> None:
        assert parse_output_language("en") is VoiceOutputLanguage.ENGLISH
        assert parse_output_language("HI") is VoiceOutputLanguage.HINDI

    def test_unsupported_value_raises(self) -> None:
        with pytest.raises(VoiceLanguageError):
            parse_output_language("auto")


class TestIsSupportedSpokenLanguage:
    def test_en_and_hi_are_supported(self) -> None:
        assert is_supported_spoken_language("en") is True
        assert is_supported_spoken_language("hi") is True

    def test_auto_follow_input_none_and_other_languages_are_not(self) -> None:
        assert is_supported_spoken_language("auto") is False
        assert is_supported_spoken_language("follow_input") is False
        assert is_supported_spoken_language(None) is False
        assert is_supported_spoken_language("fr") is False


class TestVoiceLanguagePreferenceStore:
    def test_defaults_are_auto_input_and_follow_input_output(self) -> None:
        store = VoiceLanguagePreferenceStore()
        preference = store.get()

        assert preference.input_language is VoiceInputLanguage.AUTO
        assert preference.output_language is VoiceOutputLanguage.FOLLOW_INPUT
        assert preference.last_detected_input_language is None

    def test_set_input_language_updates_current_preference(self) -> None:
        store = VoiceLanguagePreferenceStore()
        store.set_input_language(VoiceInputLanguage.HINDI)

        assert store.get().input_language is VoiceInputLanguage.HINDI

    def test_set_output_language_updates_current_preference(self) -> None:
        store = VoiceLanguagePreferenceStore()
        store.set_output_language(VoiceOutputLanguage.ENGLISH)

        assert store.get().output_language is VoiceOutputLanguage.ENGLISH

    def test_record_detected_input_language_stores_supported_languages(self) -> None:
        store = VoiceLanguagePreferenceStore()
        store.record_detected_input_language("hi")

        assert store.get().last_detected_input_language == "hi"

    def test_record_detected_input_language_ignores_unsupported_languages(self) -> None:
        store = VoiceLanguagePreferenceStore()
        store.record_detected_input_language("hi")
        store.record_detected_input_language("fr")

        # An unsupported detection never overwrites/poisons the last
        # *supported* value.
        assert store.get().last_detected_input_language == "hi"

    def test_resolve_input_language_prefers_explicit_over_preference(self) -> None:
        store = VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(input_language=VoiceInputLanguage.HINDI)
        )

        assert store.resolve_input_language(explicit="en") is VoiceInputLanguage.ENGLISH

    def test_resolve_input_language_falls_back_to_current_preference(self) -> None:
        store = VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(input_language=VoiceInputLanguage.HINDI)
        )

        assert store.resolve_input_language(explicit=None) is VoiceInputLanguage.HINDI

    def test_resolve_output_language_prefers_explicit(self) -> None:
        store = VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(output_language=VoiceOutputLanguage.HINDI)
        )

        assert store.resolve_output_language(explicit="en") == "en"

    def test_resolve_output_language_uses_concrete_preference(self) -> None:
        store = VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(output_language=VoiceOutputLanguage.HINDI)
        )

        assert store.resolve_output_language(explicit=None) == "hi"

    def test_resolve_output_language_follow_input_uses_last_detected(self) -> None:
        store = VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(
                output_language=VoiceOutputLanguage.FOLLOW_INPUT
            )
        )
        store.record_detected_input_language("hi")

        assert store.resolve_output_language(explicit=None) == "hi"

    def test_resolve_output_language_follow_input_falls_back_to_default(self) -> None:
        store = VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(
                output_language=VoiceOutputLanguage.FOLLOW_INPUT
            )
        )

        assert store.resolve_output_language(explicit=None) == DEFAULT_FALLBACK_LANGUAGE

    def test_resolve_output_language_ignores_unsupported_explicit_value(self) -> None:
        """
        An explicit value this store cannot validate as a bare
        request-level override (e.g. already-invalid input from a
        caller that bypassed schema validation) must not silently
        become the resolved language -- it falls through to the
        current preference instead.
        """

        store = VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(output_language=VoiceOutputLanguage.HINDI)
        )

        assert store.resolve_output_language(explicit="fr") == "hi"
