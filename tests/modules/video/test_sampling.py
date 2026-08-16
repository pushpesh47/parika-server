from __future__ import annotations

from parika.modules.video.sampling import (
    SamplingRequest,
    dense_indices,
    focus_window_indices,
    interval_indices,
    resolve_indices,
    timestamp_indices,
    uniform_indices,
)


class TestUniformIndices:
    def test_returns_zero_for_unknown_frame_count(self) -> None:
        assert uniform_indices(frame_count=None, max_frames=5) == [0]

    def test_returns_single_middle_index_for_one_frame_request(self) -> None:
        assert uniform_indices(frame_count=100, max_frames=1) == [50]

    def test_spans_full_range_evenly(self) -> None:
        indices = uniform_indices(frame_count=100, max_frames=5)

        assert indices[0] == 0
        assert indices[-1] == 99
        assert len(indices) <= 5

    def test_never_exceeds_frame_count(self) -> None:
        indices = uniform_indices(frame_count=3, max_frames=10)

        assert all(0 <= index < 3 for index in indices)


class TestIntervalIndices:
    def test_one_frame_every_interval(self) -> None:
        indices = interval_indices(frame_count=100, frame_rate=10.0, interval_seconds=1.0)

        assert indices == list(range(0, 100, 10))

    def test_unknown_frame_count_returns_zero(self) -> None:
        assert interval_indices(frame_count=None, frame_rate=10.0, interval_seconds=1.0) == [0]


class TestTimestampIndices:
    def test_converts_timestamps_to_indices(self) -> None:
        indices = timestamp_indices(
            frame_rate=10.0, frame_count=100, timestamps_seconds=[0.0, 1.5, 9.9]
        )

        assert indices == [0, 15, 99]

    def test_clamps_to_last_frame(self) -> None:
        indices = timestamp_indices(frame_rate=10.0, frame_count=10, timestamps_seconds=[100.0])

        assert indices == [9]


class TestDenseIndices:
    def test_denser_than_uniform_for_low_target_fps(self) -> None:
        indices = dense_indices(
            frame_count=100, frame_rate=10.0, target_fps=5.0, max_frames=50
        )

        assert len(indices) == 50

    def test_falls_back_to_uniform_when_exceeding_max_frames(self) -> None:
        indices = dense_indices(
            frame_count=1000, frame_rate=30.0, target_fps=30.0, max_frames=10
        )

        assert len(indices) <= 10


class TestFocusWindowIndices:
    def test_centers_window_on_focus_timestamp(self) -> None:
        indices = focus_window_indices(
            frame_count=1000,
            frame_rate=10.0,
            focus_timestamp_seconds=50.0,
            window_seconds=4.0,
            max_frames=10,
        )

        assert min(indices) >= 480
        assert max(indices) <= 520

    def test_clamps_to_video_bounds_near_start(self) -> None:
        indices = focus_window_indices(
            frame_count=100,
            frame_rate=10.0,
            focus_timestamp_seconds=0.0,
            window_seconds=4.0,
            max_frames=10,
        )

        assert min(indices) >= 0


class TestResolveIndices:
    def test_explicit_frame_indices_take_precedence(self) -> None:
        request = SamplingRequest(frame_indices=(5, 1, 9))
        indices = resolve_indices(
            request, frame_count=100, frame_rate=10.0, default_max_frames=8, hard_cap=8
        )

        assert indices == [1, 5, 9]

    def test_falls_back_to_uniform_when_no_override(self) -> None:
        request = SamplingRequest()
        indices = resolve_indices(
            request, frame_count=100, frame_rate=10.0, default_max_frames=4, hard_cap=8
        )

        assert len(indices) <= 4

    def test_max_frames_is_bounded_by_hard_cap(self) -> None:
        request = SamplingRequest(max_frames=1000)
        indices = resolve_indices(
            request, frame_count=100, frame_rate=10.0, default_max_frames=4, hard_cap=8
        )

        assert len(indices) <= 8

    def test_focus_timestamp_override(self) -> None:
        request = SamplingRequest(focus_timestamp_seconds=5.0, focus_window_seconds=2.0)
        indices = resolve_indices(
            request, frame_count=100, frame_rate=10.0, default_max_frames=8, hard_cap=8
        )

        assert indices
        assert all(30 <= index <= 70 for index in indices)
