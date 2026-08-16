"""
PARIKA Coding Tool - Patch Rendering

Pure, stdlib-only (`difflib`) rendering of a `TextEdit` sequence into a
`PatchProposal`. Never performs any I/O and never applies a patch --
see docs/development/Tool_Guide.md
section 4.7: applying a patch is the caller's (typically the Coding
Agent's) responsibility, done by calling the existing, unmodified
Filesystem Tool's `filesystem.write`.
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from collections.abc import Sequence

from parika.tools.coding.exceptions import PatchGenerationError
from parika.tools.coding.model import FilePatch, PatchProposal, TextEdit


def render_patch(
    edits: Sequence[TextEdit],
    *,
    original_contents: dict[str, str],
) -> PatchProposal:
    """
    Render `edits` into a `PatchProposal`.

    Args:
        edits:
            The edits to apply, grouped internally by `file_path`.

        original_contents:
            The current, already-read content of every file touched
            by `edits`, keyed by `file_path`. Supplied by the caller
            (which already read each file, e.g. via `filesystem.read`)
            -- this function never reads a file itself.

    Raises:
        PatchGenerationError:
            If an edit references a file not present in
            `original_contents`, or if an edit's `old_text` does not
            match the file's actual content at the given location.
    """

    edits_by_file: dict[str, list[TextEdit]] = defaultdict(list)

    for edit in edits:
        edits_by_file[edit.file_path].append(edit)

    files: list[FilePatch] = []

    for file_path, file_edits in edits_by_file.items():
        if file_path not in original_contents:
            raise PatchGenerationError(
                f"No original content was supplied for '{file_path}'."
            )

        original = original_contents[file_path]
        new_content = _apply_edits(file_path, original, file_edits)
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=file_path,
                tofile=file_path,
            )
        )

        files.append(
            FilePatch(file_path=file_path, diff=diff, new_content=new_content)
        )

    return PatchProposal(files=tuple(files))


def _apply_edits(
    file_path: str, original: str, edits: list[TextEdit]
) -> str:
    lines = original.splitlines(keepends=True)

    # Apply from the bottom of the file upward so earlier edits never
    # shift the line numbers later edits reference.
    for edit in sorted(edits, key=lambda item: (item.line, item.column), reverse=True):
        line_index = edit.line - 1

        if line_index < 0 or line_index >= len(lines):
            raise PatchGenerationError(
                f"Edit targets line {edit.line} of '{file_path}', which "
                f"is out of range (file has {len(lines)} line(s))."
            )

        line = lines[line_index]

        if edit.old_text and edit.old_text not in line:
            raise PatchGenerationError(
                f"Edit's old_text '{edit.old_text}' was not found on "
                f"line {edit.line} of '{file_path}'."
            )

        lines[line_index] = line.replace(edit.old_text, edit.new_text, 1)

    return "".join(lines)
