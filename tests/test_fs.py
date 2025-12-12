# pyright: standard
from pathlib import Path

import pytest

from aico.fs import get_context_file_contents, validate_input_paths


def test_get_context_file_contents_only_includes_existing_and_warns_for_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # GIVEN a session root and some files on disk
    session_root = tmp_path
    (session_root / "existing.py").write_text("def foo(): pass")
    (session_root / "sub").mkdir()
    (session_root / "sub" / "another.py").write_text("print('hi')")
    (session_root / "dir_in_ctx").mkdir()

    # AND a context_files list with existing, missing, and directory paths
    context_files = [
        "existing.py",
        "missing.txt",
        "sub/another.py",
        "sub/also_missing.md",
        "dir_in_ctx",
    ]

    # WHEN building the original file contents
    contents = get_context_file_contents(context_files, session_root)

    # THEN the returned dictionary only contains content for existing files
    assert sorted(list(contents.keys())) == sorted(["existing.py", "sub/another.py"])
    assert contents["existing.py"] == "def foo(): pass"
    assert contents["sub/another.py"] == "print('hi')"

    # AND warnings are printed to stderr for each missing or non-file path
    captured = capsys.readouterr()
    err_output = captured.err
    assert "Warning: Context files not found, skipping: dir_in_ctx missing.txt sub/also_missing.md" in err_output
    assert "existing.py" not in err_output
    assert "another.py" not in err_output


def test_get_context_file_contents_handles_empty_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # GIVEN an empty context_files list
    context_files: list[str] = []

    # WHEN building contents
    contents = get_context_file_contents(context_files, tmp_path)

    # THEN the result is an empty dictionary and no warnings are printed
    assert contents == {}
    captured = capsys.readouterr()
    assert captured.err == ""


def test_validate_input_paths_normalizes_relative_traversals(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verifies that `validate_input_paths` normalizes relative paths
    even when traversing up from the current working directory.
    """
    # GIVEN a session root and a file
    session_root = tmp_path
    target_file = session_root / "target.txt"
    target_file.write_text("content")

    # AND a subdirectory exists
    subdir = session_root / "subdir"
    subdir.mkdir()

    # AND the current working directory is the SUBDIR (crucial for this test)
    monkeypatch.chdir(subdir)

    # WHEN validating a path that traverses back up (e.g. "../target.txt")
    input_paths = [Path("../target.txt")]
    valid_rels, has_errors = validate_input_paths(session_root, input_paths)

    # THEN the path is normalized to just the filename, not "subdir/../target.txt"
    assert valid_rels == ["target.txt"]
    assert not has_errors

    # AND no errors are printed
    captured = capsys.readouterr()
    assert captured.err == ""
