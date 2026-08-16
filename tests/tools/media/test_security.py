"""
Unit tests for `LocalMediaPathSecurity` - the choke point confining
local `media.play` resolution to `[media].allowed_local_roots`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.tools.media.exceptions import MediaPathNotAllowedError, MediaValidationError
from parika.tools.media.security import LocalMediaPathSecurity, LocalMediaPathSecurityConfig


class TestLocalMediaPathSecurity:
    def test_disabled_by_default_denies_every_path(self, tmp_path: Path) -> None:
        security = LocalMediaPathSecurity(LocalMediaPathSecurityConfig())

        with pytest.raises(MediaPathNotAllowedError):
            security.resolve(str(tmp_path / "song.mp3"))

    def test_allows_a_path_under_a_configured_root(self, tmp_path: Path) -> None:
        music_dir = tmp_path / "Music"
        music_dir.mkdir()
        song = music_dir / "song.mp3"
        song.touch()

        security = LocalMediaPathSecurity(
            LocalMediaPathSecurityConfig(allowed_roots=(music_dir,))
        )

        resolved = security.resolve(str(song))
        assert resolved == song.resolve()

    def test_denies_a_path_outside_every_configured_root(self, tmp_path: Path) -> None:
        music_dir = tmp_path / "Music"
        music_dir.mkdir()
        outside_file = tmp_path / "secret.txt"
        outside_file.touch()

        security = LocalMediaPathSecurity(
            LocalMediaPathSecurityConfig(allowed_roots=(music_dir,))
        )

        with pytest.raises(MediaPathNotAllowedError):
            security.resolve(str(outside_file))

    def test_denies_traversal_outside_the_root(self, tmp_path: Path) -> None:
        music_dir = tmp_path / "Music"
        music_dir.mkdir()
        (tmp_path / "secret.txt").touch()

        security = LocalMediaPathSecurity(
            LocalMediaPathSecurityConfig(allowed_roots=(music_dir,))
        )

        with pytest.raises(MediaPathNotAllowedError):
            security.resolve(str(music_dir / ".." / "secret.txt"))

    def test_rejects_non_string_input(self) -> None:
        security = LocalMediaPathSecurity(LocalMediaPathSecurityConfig())

        with pytest.raises(MediaValidationError):
            security.resolve(123)  # type: ignore[arg-type]

        with pytest.raises(MediaValidationError):
            security.resolve("   ")

    def test_relative_path_resolves_against_first_root(self, tmp_path: Path) -> None:
        music_dir = tmp_path / "Music"
        music_dir.mkdir()
        (music_dir / "song.mp3").touch()

        security = LocalMediaPathSecurity(
            LocalMediaPathSecurityConfig(allowed_roots=(music_dir,))
        )

        resolved = security.resolve("song.mp3")
        assert resolved == (music_dir / "song.mp3").resolve()
