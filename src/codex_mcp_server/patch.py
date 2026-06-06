from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PatchError(Exception):
    pass


@dataclass
class UpdateChunk:
    change_context: str | None
    old_lines: list[str]
    new_lines: list[str]
    is_end_of_file: bool = False


@dataclass
class Hunk:
    kind: str
    path: str
    contents: str = ""
    move_path: str | None = None
    chunks: list[UpdateChunk] | None = None

    @property
    def affected_path(self) -> str:
        return self.move_path or self.path


BEGIN = "*** Begin Patch"
END = "*** End Patch"
ADD = "*** Add File: "
DELETE = "*** Delete File: "
UPDATE = "*** Update File: "
MOVE = "*** Move to: "
EOF_MARKER = "*** End of File"


def apply_patch_text(patch: str, cwd: Path) -> dict[str, object]:
    hunks = parse_patch(patch)
    if not hunks:
        raise PatchError("No files were modified.")

    added: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []

    for hunk in hunks:
        target = resolve_patch_path(cwd, hunk.path)
        if hunk.kind == "add":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(hunk.contents, encoding="utf-8")
            added.append(hunk.path)
        elif hunk.kind == "delete":
            if not target.exists():
                raise PatchError(f"Failed to delete file {target}: file does not exist")
            if target.is_dir():
                raise PatchError(f"Failed to delete file {target}: path is a directory")
            target.unlink()
            deleted.append(hunk.path)
        elif hunk.kind == "update":
            if hunk.chunks is None:
                raise PatchError(f"Update file hunk for path '{hunk.path}' is empty")
            if not target.exists():
                raise PatchError(f"Failed to read file to update {target}: file does not exist")
            if target.is_dir():
                raise PatchError(f"Failed to read file to update {target}: path is a directory")
            original = target.read_text(encoding="utf-8")
            new_content = derive_new_contents(original, hunk.chunks, target)
            if hunk.move_path:
                destination = resolve_patch_path(cwd, hunk.move_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(new_content, encoding="utf-8")
                target.unlink()
            else:
                target.write_text(new_content, encoding="utf-8")
            modified.append(hunk.affected_path)
        else:
            raise PatchError(f"Unknown hunk type: {hunk.kind}")

    summary_lines = ["Success. Updated the following files:"]
    summary_lines.extend(f"A {path}" for path in added)
    summary_lines.extend(f"M {path}" for path in modified)
    summary_lines.extend(f"D {path}" for path in deleted)
    return {
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "summary": "\n".join(summary_lines) + "\n",
    }


def parse_patch(patch: str) -> list[Hunk]:
    lines = patch.strip().splitlines()
    lines = strip_heredoc(lines)
    if not lines or lines[0].strip() != BEGIN:
        raise PatchError("The first line of the patch must be '*** Begin Patch'")
    if len(lines) < 2 or lines[-1].strip() != END:
        raise PatchError("The last line of the patch must be '*** End Patch'")

    hunks: list[Hunk] = []
    body = lines[1:-1]
    index = 0
    if body and body[0].lstrip().startswith("*** Environment ID: "):
        index += 1

    while index < len(body):
        line = body[index].strip()
        if not line:
            index += 1
            continue
        hunk, consumed = parse_one_hunk(body[index:], index + 2)
        hunks.append(hunk)
        index += consumed
    return hunks


def strip_heredoc(lines: list[str]) -> list[str]:
    if len(lines) >= 4 and lines[0] in {"<<EOF", "<<'EOF'", '<<"EOF"'} and lines[-1].endswith("EOF"):
        return lines[1:-1]
    return lines


def parse_one_hunk(lines: list[str], line_number: int) -> tuple[Hunk, int]:
    first = lines[0].strip()
    if first.startswith(ADD):
        path = first[len(ADD) :]
        contents: list[str] = []
        consumed = 1
        for line in lines[1:]:
            if not line.startswith("+"):
                break
            contents.append(line[1:])
            consumed += 1
        if consumed == 1:
            raise PatchError(f"Invalid patch hunk on line {line_number}: Add file hunk is empty")
        return Hunk(kind="add", path=path, contents="\n".join(contents) + "\n"), consumed

    if first.startswith(DELETE):
        return Hunk(kind="delete", path=first[len(DELETE) :]), 1

    if first.startswith(UPDATE):
        path = first[len(UPDATE) :]
        consumed = 1
        move_path = None
        remaining = lines[1:]
        if remaining and remaining[0].startswith(MOVE):
            move_path = remaining[0][len(MOVE) :]
            consumed += 1
            remaining = remaining[1:]

        chunks: list[UpdateChunk] = []
        while remaining:
            if not remaining[0].strip():
                consumed += 1
                remaining = remaining[1:]
                continue
            if remaining[0].startswith("*** "):
                break
            chunk, chunk_lines = parse_update_chunk(
                remaining,
                line_number + consumed,
                allow_missing_context=not chunks,
            )
            chunks.append(chunk)
            consumed += chunk_lines
            remaining = remaining[chunk_lines:]
        if not chunks:
            raise PatchError(
                f"Invalid patch hunk on line {line_number}: Update file hunk for path '{path}' is empty"
            )
        return Hunk(kind="update", path=path, move_path=move_path, chunks=chunks), consumed

    raise PatchError(
        "Invalid patch hunk on line "
        f"{line_number}: '{first}' is not a valid hunk header. "
        "Valid hunk headers: '*** Add File: {path}', "
        "'*** Delete File: {path}', '*** Update File: {path}'"
    )


def parse_update_chunk(
    lines: list[str], line_number: int, allow_missing_context: bool
) -> tuple[UpdateChunk, int]:
    if not lines:
        raise PatchError(f"Invalid patch hunk on line {line_number}: Update hunk is empty")

    if lines[0] == "@@":
        change_context = None
        start_index = 1
    elif lines[0].startswith("@@ "):
        change_context = lines[0][3:]
        start_index = 1
    elif allow_missing_context:
        change_context = None
        start_index = 0
    else:
        raise PatchError(
            f"Invalid patch hunk on line {line_number}: Expected update hunk to start with @@"
        )

    old_lines: list[str] = []
    new_lines: list[str] = []
    consumed = 0
    is_end_of_file = False
    for line in lines[start_index:]:
        if line == EOF_MARKER:
            if consumed == 0:
                raise PatchError(
                    f"Invalid patch hunk on line {line_number + start_index}: Update hunk has no lines"
                )
            is_end_of_file = True
            consumed += 1
            break
        if line == "":
            old_lines.append("")
            new_lines.append("")
        elif line.startswith(" "):
            old_lines.append(line[1:])
            new_lines.append(line[1:])
        elif line.startswith("+"):
            new_lines.append(line[1:])
        elif line.startswith("-"):
            old_lines.append(line[1:])
        else:
            if consumed == 0:
                raise PatchError(
                    f"Invalid patch hunk on line {line_number + start_index}: Unexpected line in update hunk: {line!r}"
                )
            break
        consumed += 1

    if consumed == 0:
        raise PatchError(f"Invalid patch hunk on line {line_number}: Update hunk has no lines")
    return UpdateChunk(change_context, old_lines, new_lines, is_end_of_file), start_index + consumed


def derive_new_contents(original: str, chunks: list[UpdateChunk], path: Path) -> str:
    original_lines = original.split("\n")
    if original_lines and original_lines[-1] == "":
        original_lines.pop()
    replacements = compute_replacements(original_lines, chunks, path)
    new_lines = apply_replacements(original_lines, replacements)
    if not new_lines or new_lines[-1] != "":
        new_lines.append("")
    return "\n".join(new_lines)


def compute_replacements(
    original_lines: list[str], chunks: list[UpdateChunk], path: Path
) -> list[tuple[int, int, list[str]]]:
    replacements: list[tuple[int, int, list[str]]] = []
    line_index = 0
    for chunk in chunks:
        if chunk.change_context is not None:
            context_index = seek_sequence(original_lines, [chunk.change_context], line_index, False)
            if context_index is None:
                raise PatchError(f"Failed to find context '{chunk.change_context}' in {path}")
            line_index = context_index + 1

        if not chunk.old_lines:
            insert_at = len(original_lines)
            replacements.append((insert_at, 0, list(chunk.new_lines)))
            continue

        pattern = list(chunk.old_lines)
        new_slice = list(chunk.new_lines)
        found = seek_sequence(original_lines, pattern, line_index, chunk.is_end_of_file)
        if found is None and pattern and pattern[-1] == "":
            pattern = pattern[:-1]
            if new_slice and new_slice[-1] == "":
                new_slice = new_slice[:-1]
            found = seek_sequence(original_lines, pattern, line_index, chunk.is_end_of_file)
        if found is None:
            expected = "\n".join(chunk.old_lines)
            raise PatchError(f"Failed to find expected lines in {path}:\n{expected}")
        replacements.append((found, len(pattern), new_slice))
        line_index = found + len(pattern)
    return sorted(replacements, key=lambda item: item[0])


def apply_replacements(
    lines: list[str], replacements: list[tuple[int, int, list[str]]]
) -> list[str]:
    result = list(lines)
    for start, old_len, new_segment in reversed(replacements):
        result[start : start + old_len] = new_segment
    return result


def seek_sequence(lines: list[str], pattern: list[str], start: int, eof: bool) -> int | None:
    if not pattern:
        return len(lines)
    max_start = len(lines) - len(pattern)
    for index in range(start, max_start + 1):
        if lines[index : index + len(pattern)] == pattern:
            if eof and index + len(pattern) != len(lines):
                continue
            return index
    return None


def resolve_patch_path(cwd: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()
