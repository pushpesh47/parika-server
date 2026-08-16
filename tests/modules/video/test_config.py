from __future__ import annotations

from parika.core.configuration.configuration import Configuration
from parika.modules.video.config import (
    VideoToolConfig,
    load_video_config,
    opencv_dependency_available,
)


def test_load_video_config_returns_defaults_when_configuration_is_none() -> None:
    config = load_video_config(None)

    assert config == VideoToolConfig()


def test_load_video_config_reads_overrides(configuration: Configuration) -> None:
    configuration._config = {  # noqa: SLF001
        "video": {
            "enabled": False,
            "max_sample_frames": 10,
            "scene_change_threshold": 0.5,
        }
    }

    config = load_video_config(configuration)

    assert config.enabled is False
    assert config.max_sample_frames == 10
    assert config.scene_change_threshold == 0.5


def test_opencv_dependency_available_matches_import() -> None:
    try:
        import cv2  # noqa: F401

        assert opencv_dependency_available() is True
    except ImportError:
        assert opencv_dependency_available() is False
