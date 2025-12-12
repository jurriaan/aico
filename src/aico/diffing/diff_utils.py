import difflib


def _quote_filename_if_needed(filename: str) -> str:
    """Quotes a filename if it contains spaces, for use in a diff header."""
    return f'"{filename}"' if " " in filename else filename


def _add_no_newline_marker_if_needed(diff_lines: list[str], original_content: str | None) -> None:
    """
    Manually injects the '\\ No newline at end of file' marker into a diff list IN-PLACE.
    This is a workaround because `difflib` doesn't add the marker itself when using
    `splitlines(keepends=True)`.

    The logic is: if the original file lacks a trailing newline, find the last line
    in the diff that came from the original file (' ' or '-'). If that diff line
    also lacks a trailing newline, it must be the end of the file, so we add the marker.
    """
    if not (diff_lines and original_content and not original_content.endswith("\n")):
        return

    # Iterate backwards through the diff to find the last line from the original file
    for i in range(len(diff_lines) - 1, -1, -1):
        line = diff_lines[i]

        if line.startswith("@@"):
            # We've reached the start of a hunk without finding a suitable line.
            # This means the hunk doesn't contain lines from the end of the original file.
            return

        if line.startswith("-") or line.startswith(" "):
            # This is the last relevant line from the original file within this hunk.
            # If it doesn't end with a newline, then it must be the end of the file.
            if not line.endswith("\n"):
                diff_lines[i] += "\n"
                diff_lines.insert(i + 1, "\\ No newline at end of file\n")
            # If it *does* end with a newline, the hunk is not at the end of the file,
            # so we shouldn't add a marker. In either case, we are done with this hunk.
            return


def generate_diff_with_no_newline_handling(
    from_file: str,
    to_file: str,
    from_content: str | None,
    to_content: str | None,
) -> list[str]:
    """
    Generates a unified diff using difflib and applies custom logic to handle
    the '\\ No newline at end of file' marker, which difflib does not do correctly
    with splitlines(keepends=True).
    """
    from_lines = (from_content or "").splitlines(keepends=True)
    to_lines = (to_content or "").splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            from_lines,
            to_lines,
            fromfile=_quote_filename_if_needed(from_file),
            tofile=_quote_filename_if_needed(to_file),
        )
    )

    _add_no_newline_marker_if_needed(diff_lines, from_content)

    return diff_lines
