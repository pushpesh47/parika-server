"""
PARIKA Vision Module - Multi-Image Collection Drivers

`VisionFindSimilarImagesToolDriver` (`vision.find_similar_images`) and
`VisionFindDuplicatesToolDriver` (`vision.find_duplicates`) rank/group
a candidate set of images by the same deterministic
`hashing.compare_images()`/perceptual-hash machinery
`vision.compare_images` uses for a single pair -- never a model call
to *find* similar/duplicate images; only an optional, opt-in
`verify_with_model` narration on the winning result(s) afterwards.

`VisionSearchImagesToolDriver` (`vision.search_images`) is the one
Capability in this trio that is genuinely, unavoidably semantic --
"find images showing X" requires recognizing *what* each image shows,
which no deterministic algorithm in this codebase can do without a
trained image-embedding/captioning model. It asks its own Provider-
backed Capability a bounded yes/no question per candidate (capped by
`max_candidates`/`[vision].max_search_candidates`, the compute-
minimization guard this Capability needs precisely because it is the
one genuinely model-per-candidate Capability here).

Every candidate set is resolved via `paths` (an explicit list) or
`directory` (+ optional `pattern`), the latter through the existing,
unmodified `filesystem.list` Capability
(`engine.list_image_paths()`) -- never a direct filesystem walk.
"""

from __future__ import annotations

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine, hashing
from .exceptions import VisionImageReadError

_DEFAULT_TOP_K = 10
_DEFAULT_MAX_SEARCH_CANDIDATES = 20
_SEARCH_MATCH_TOKEN = "MATCH"


def _resolve_candidate_paths(brain, request: ToolRequest) -> list[str]:
    paths = request.arguments.get("paths")

    if isinstance(paths, (list, tuple)) and paths:
        return [str(path) for path in paths]

    directory = str(request.arguments.get("directory", "")).strip()

    if directory:
        pattern = request.arguments.get("pattern")
        return engine.list_image_paths(
            brain, directory, pattern=str(pattern) if pattern else None
        )

    raise VisionImageReadError(
        "request.arguments must supply either a non-empty 'paths' "
        "list or a 'directory' string."
    )


class VisionFindSimilarImagesToolDriver:
    """`ToolDriver` implementing `vision.find_similar_images`."""

    def __init__(
        self,
        *,
        brain,
        provider_capability_id: str,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._provider_capability_id = provider_capability_id
        self._progress = progress_reporter or NullProgressReporter(
            "vision.find_similar_images"
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        reference_path = str(request.arguments.get("reference_path", "")).strip()

        if not reference_path:
            raise VisionImageReadError(
                "request.arguments['reference_path'] must be a "
                "non-empty string."
            )

        top_k = int(request.arguments.get("top_k", _DEFAULT_TOP_K))
        verify_with_model = bool(request.arguments.get("verify_with_model", False))

        self._progress.started(message="Reading reference image...")

        reference_base64 = engine.read_image_base64(self._brain, reference_path)
        reference_image = engine.decode_base64_image(reference_base64)

        candidate_paths = [
            path
            for path in _resolve_candidate_paths(self._brain, request)
            if path != reference_path
        ]

        self._progress.progress(
            message=f"Comparing against {len(candidate_paths)} candidate(s)..."
        )

        matches: list[dict] = []

        for path in candidate_paths:
            try:
                candidate_base64 = engine.read_image_base64(self._brain, path)
                candidate_image = engine.decode_base64_image(candidate_base64)
            except VisionImageReadError:
                continue

            comparison = hashing.compare_images(reference_image, candidate_image)
            matches.append(
                {
                    "path": path,
                    "overall_similarity": comparison.overall_similarity,
                    "perceptual_hash_similarity": comparison.perceptual_hash_similarity,
                    "pixel_similarity": comparison.pixel_similarity,
                    "histogram_similarity": comparison.histogram_similarity,
                }
            )

        matches.sort(key=lambda entry: -entry["overall_similarity"])
        top_matches = matches[: max(0, top_k)]

        if verify_with_model and top_matches:
            self._progress.progress(message="Waiting for Vision model...")
            best_path = top_matches[0]["path"]
            best_base64 = engine.read_image_base64(self._brain, best_path)
            top_matches[0]["explanation"] = engine.analyze_with_provider(
                self._brain,
                self._provider_capability_id,
                (reference_base64, best_base64),
                "Describe how similar these two images are and why.",
                execution_requirements=request.metadata.get(
                    "execution_requirements"
                ),
            )

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={"matches": top_matches, "candidates_checked": len(matches)},
            attributes={"reference_path": reference_path},
        )


class VisionFindDuplicatesToolDriver:
    """`ToolDriver` implementing `vision.find_duplicates`."""

    def __init__(
        self,
        *,
        brain,
        provider_capability_id: str,
        progress_reporter: ProgressReporter | None = None,
        duplicate_hamming_distance: int = 5,
    ) -> None:
        self._brain = brain
        self._provider_capability_id = provider_capability_id
        self._progress = progress_reporter or NullProgressReporter(
            "vision.find_duplicates"
        )
        self._duplicate_hamming_distance = duplicate_hamming_distance

    def execute(self, request: ToolRequest) -> ToolResponse:
        verify_with_model = bool(request.arguments.get("verify_with_model", False))
        candidate_paths = _resolve_candidate_paths(self._brain, request)

        self._progress.started(
            message=f"Hashing {len(candidate_paths)} image(s)..."
        )

        hashes: dict[str, int] = {}

        for path in candidate_paths:
            try:
                image_base64 = engine.read_image_base64(self._brain, path)
                image = engine.decode_base64_image(image_base64)
            except VisionImageReadError:
                continue

            hashes[path] = hashing.difference_hash(image)

        self._progress.progress(message="Grouping near-duplicates...")

        groups = _group_by_hamming_distance(hashes, self._duplicate_hamming_distance)

        if verify_with_model and groups:
            self._progress.progress(message="Waiting for Vision model...")
            first_group = groups[0]
            base64_images = tuple(
                engine.read_image_base64(self._brain, path) for path in first_group[:2]
            )
            groups_result = [
                {
                    "paths": list(group),
                    "explanation": (
                        engine.analyze_with_provider(
                            self._brain,
                            self._provider_capability_id,
                            base64_images,
                            "Are these images duplicates or near-duplicates of each other? Explain briefly.",
                            execution_requirements=request.metadata.get(
                                "execution_requirements"
                            ),
                        )
                        if group is first_group
                        else None
                    ),
                }
                for group in groups
            ]
        else:
            groups_result = [{"paths": list(group)} for group in groups]

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={"duplicate_groups": groups_result, "images_checked": len(hashes)},
            attributes={},
        )


def _group_by_hamming_distance(
    hashes: dict[str, int], max_distance: int
) -> list[tuple[str, ...]]:
    """Union-find grouping of `hashes` into clusters where every member is
    within `max_distance` Hamming distance of at least one other member."""

    paths = list(hashes.keys())
    parent = {path: path for path in paths}

    def find(path: str) -> str:
        while parent[path] != path:
            path = parent[path]
        return path

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    for i, path_a in enumerate(paths):
        for path_b in paths[i + 1 :]:
            if hashing.hamming_distance(hashes[path_a], hashes[path_b]) <= max_distance:
                union(path_a, path_b)

    clusters: dict[str, list[str]] = {}
    for path in paths:
        clusters.setdefault(find(path), []).append(path)

    return [tuple(members) for members in clusters.values() if len(members) > 1]


class VisionSearchImagesToolDriver:
    """`ToolDriver` implementing `vision.search_images`."""

    def __init__(
        self,
        *,
        brain,
        provider_capability_id: str,
        progress_reporter: ProgressReporter | None = None,
        max_candidates: int = _DEFAULT_MAX_SEARCH_CANDIDATES,
    ) -> None:
        self._brain = brain
        self._provider_capability_id = provider_capability_id
        self._progress = progress_reporter or NullProgressReporter(
            "vision.search_images"
        )
        self._max_candidates = max_candidates

    def execute(self, request: ToolRequest) -> ToolResponse:
        query = str(request.arguments.get("query", "")).strip()

        if not query:
            raise VisionImageReadError(
                "request.arguments['query'] must be a non-empty string."
            )

        max_candidates = int(
            request.arguments.get("max_candidates", self._max_candidates)
        )
        candidate_paths = _resolve_candidate_paths(self._brain, request)
        bounded_paths = candidate_paths[: max(0, max_candidates)]

        self._progress.started(
            message=f"Checking {len(bounded_paths)} candidate(s)..."
        )

        instruction = (
            f"Does this image show: {query}? Respond with exactly one "
            f"word first, either '{_SEARCH_MATCH_TOKEN}' or "
            "'NO_MATCH', followed by a short justification."
        )

        matches: list[dict] = []

        for path in bounded_paths:
            try:
                image_base64 = engine.read_image_base64(self._brain, path)
            except VisionImageReadError:
                continue

            self._progress.progress(message=f"Checking {path}...")

            text = engine.analyze_with_provider(
                self._brain,
                self._provider_capability_id,
                (image_base64,),
                instruction,
                execution_requirements=request.metadata.get(
                    "execution_requirements"
                ),
            )

            if text.strip().upper().startswith(_SEARCH_MATCH_TOKEN):
                matches.append({"path": path, "justification": text.strip()})

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={
                "query": query,
                "matches": matches,
                "candidates_checked": len(bounded_paths),
                "candidates_available": len(candidate_paths),
            },
            attributes={},
        )
