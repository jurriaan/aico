import os
import sys
from pathlib import Path

from aico.models import FileContents


def validate_input_paths(
    session_root: Path,
    file_paths: list[Path],
    require_file_exists: bool = True,
) -> tuple[list[str], bool]:
    """
    Validates a list of input file paths relative to the session root.

    - Resolves paths relative to CWD.
    - precise security check: prevents path traversal (must be inside root).
    - converts to relative paths from session root.
    - optional existence check.

    Returns a tuple: (list of valid relative path strings, has_errors boolean).
    """
    valid_rels: list[str] = []
    has_errors = False

    for path in file_paths:
        # 1. Resolve to absolute path
        # We use absolute() to preserve symlinks in the path name,
        # but we use os.path.normpath to collapse '..' and '.' segments lexically.
        abs_path = Path(os.path.normpath(path.absolute()))
        resolved_path = path.resolve()

        # 2. Security check: Is it inside the session root?
        try:
            # Ensure the actual content (target) is inside the root
            _ = resolved_path.relative_to(session_root)
            # Ensure the logical path is inside the root
            rel_path = abs_path.relative_to(session_root)
        except ValueError:
            # Use resolved path for the error message to explain why it failed if it was a symlink context
            print(
                f"Error: File '{resolved_path}' is outside the session root '{session_root}'",
                file=sys.stderr,
            )
            has_errors = True
            continue

        rel_path_str = rel_path.as_posix()

        # 3. Existence check (optional)
        if require_file_exists and not abs_path.is_file():
            print(f"Error: File not found: {rel_path_str}", file=sys.stderr)
            has_errors = True
            continue

        valid_rels.append(rel_path_str)

    return valid_rels, has_errors


def read_file_safe(path: Path) -> str | None:
    """
    Safely reads a file as UTF-8 text, returning None on OSError or UnicodeDecodeError.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def get_context_file_contents(
    context_files: list[str],
    session_root: Path,
) -> FileContents:
    """
    Reads the contents of context files relative to the session root.

    Skips missing or unreadable files with a warning to stderr.
    Returns a mapping of relative path strings to file contents.
    """
    contents: FileContents = {}
    missing_files: list[str] = []

    for rel_path_str in context_files:
        abs_path = session_root / rel_path_str
        content = read_file_safe(abs_path)
        if content is not None:
            contents[rel_path_str] = content
        else:
            missing_files.append(rel_path_str)

    if missing_files:
        print(
            f"Warning: Context files not found, skipping: {' '.join(sorted(missing_files))}",
            file=sys.stderr,
        )

    return contents
