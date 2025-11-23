# pyright: standard

import json
from pathlib import Path

from typer.testing import CliRunner

from aico.lib.session_find import complete_files_in_context
from aico.main import app

runner = CliRunner()


def test_add_file_to_context(tmp_path: Path) -> None:
    # GIVEN an initialized session and a file to add
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        test_file = Path(td) / "test_file.py"
        test_file.write_text("print('hello')")

        # WHEN `aico add` is run with the file path
        result = runner.invoke(app, ["add", "test_file.py"])

        # THEN the command succeeds and reports the addition
        assert result.exit_code == 0
        assert "Added file to context: test_file.py" in result.stdout

        # AND the session file is updated with the file's relative path
        view_file = Path(td) / ".aico" / "sessions" / "main.json"
        view_data = json.loads(view_file.read_text())
        assert view_data["context_files"] == ["test_file.py"]


def test_add_duplicate_file_is_ignored(tmp_path: Path) -> None:
    # GIVEN a session with a file already in the context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])
        test_file = Path(td) / "test_file.py"
        test_file.write_text("print('hello')")
        # Add it once
        runner.invoke(app, ["add", str(test_file)])

        # WHEN the same file is added again
        result = runner.invoke(app, ["add", str(test_file)])

        # THEN the command reports that the file is already in context
        assert result.exit_code == 0
        assert "File already in context: test_file.py" in result.stdout

        # AND the session context list remains unchanged
        view_file = Path(td) / ".aico" / "sessions" / "main.json"
        view_data = json.loads(view_file.read_text())
        assert view_data["context_files"] == ["test_file.py"]


def test_add_non_existent_file_fails(tmp_path: Path) -> None:
    # GIVEN an initialized session
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(app, ["init"])

        # WHEN adding a file that does not exist
        result = runner.invoke(app, ["add", "non_existent_file.py"])

        # THEN the command fails with an error
        assert result.exit_code == 1
        assert "Error: File not found: non_existent_file.py" in result.stderr


def test_add_file_outside_session_root_fails(tmp_path: Path) -> None:
    # GIVEN a session in one directory and a file in a parallel directory
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    other_dir = tmp_path / "other"
    other_dir.mkdir()

    other_file = other_dir / "file.txt"
    other_file.touch()

    with runner.isolated_filesystem(temp_dir=project_dir) as td:
        runner.invoke(app, ["init"])

        # WHEN attempting to add the file using a path that goes outside the session root
        # Note: We resolve the path to be absolute to test the logic robustly.
        result = runner.invoke(app, ["add", str(other_file.resolve())])

        # THEN the command fails with a clear error message
        assert result.exit_code == 1
        assert (
            f"Error: File '{other_file.resolve()}' is outside the session root '{Path(td).resolve()}'" in result.stderr
        )


def test_add_multiple_files_successfully(tmp_path: Path) -> None:
    # GIVEN an initialized session and two files to add
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        file1 = Path(td) / "file1.py"
        file1.write_text("content1")
        file2 = Path(td) / "file2.py"
        file2.write_text("content2")

        # WHEN `aico add` is run with multiple files
        result = runner.invoke(app, ["add", "file1.py", "file2.py"])

        # THEN the command succeeds and reports both additions
        assert result.exit_code == 0
        assert "Added file to context: file1.py" in result.stdout
        assert "Added file to context: file2.py" in result.stdout

        # AND the session file is updated with both relative paths
        view_file = Path(td) / ".aico" / "sessions" / "main.json"
        view_data = json.loads(view_file.read_text())
        assert sorted(view_data["context_files"]) == ["file1.py", "file2.py"]


def test_add_multiple_files_with_one_already_in_context(tmp_path: Path) -> None:
    # GIVEN a session with one file already in context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        file1 = Path(td) / "file1.py"
        file1.write_text("content1")
        file2 = Path(td) / "file2.py"
        file2.write_text("content2")
        runner.invoke(app, ["add", "file1.py"])  # Pre-add file1

        # WHEN `aico add` is run with both the existing and a new file
        result = runner.invoke(app, ["add", "file1.py", "file2.py"])

        # THEN the command succeeds and reports the correct status for each
        assert result.exit_code == 0
        assert "File already in context: file1.py" in result.stdout
        assert "Added file to context: file2.py" in result.stdout

        # AND the session file contains both files without duplicates
        view_file = Path(td) / ".aico" / "sessions" / "main.json"
        view_data = json.loads(view_file.read_text())
        assert sorted(view_data["context_files"]) == ["file1.py", "file2.py"]


def test_add_multiple_files_with_one_non_existent_partially_fails(
    tmp_path: Path,
) -> None:
    # GIVEN an initialized session and one valid and one non-existent file
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        file1 = Path(td) / "file1.py"
        file1.write_text("content1")
        non_existent_file = "non_existent.py"

        # WHEN `aico add` is run with both files
        result = runner.invoke(app, ["add", "file1.py", non_existent_file])

        # THEN the command exits with a non-zero status code
        assert result.exit_code == 1

        # AND it reports the success for the valid file
        assert "Added file to context: file1.py" in result.stdout

        # AND it reports an error for the non-existent file
        assert f"Error: File not found: {non_existent_file}" in result.stderr

        # AND the session file is updated with only the valid file
        view_file = Path(td) / ".aico" / "sessions" / "main.json"
        view_data = json.loads(view_file.read_text())
        assert view_data["context_files"] == ["file1.py"]


def test_drop_single_file_successfully(tmp_path: Path) -> None:
    # GIVEN a session with two files in context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])
        (Path(td) / "file1.py").touch()
        (Path(td) / "file2.py").touch()
        runner.invoke(app, ["add", "file1.py", "file2.py"])

        # WHEN `aico drop` is run on one file
        result = runner.invoke(app, ["drop", "file1.py"])

        # THEN the command succeeds and reports the removal
        assert result.exit_code == 0
        assert "Dropped file from context: file1.py" in result.stdout

        # AND the session file is updated to contain only the other file
        view_file = Path(td) / ".aico" / "sessions" / "main.json"
        view_data = json.loads(view_file.read_text())
        assert sorted(view_data["context_files"]) == ["file2.py"]


def test_drop_multiple_files_successfully(tmp_path: Path) -> None:
    # GIVEN a session with three files in context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])
        (Path(td) / "file1.py").touch()
        (Path(td) / "file2.py").touch()
        (Path(td) / "file3.py").touch()
        runner.invoke(app, ["add", "file1.py", "file2.py", "file3.py"])

        # WHEN `aico drop` is run on two files
        result = runner.invoke(app, ["drop", "file1.py", "file3.py"])

        # THEN the command succeeds and reports both removals
        assert result.exit_code == 0
        assert "Dropped file from context: file1.py" in result.stdout
        assert "Dropped file from context: file3.py" in result.stdout

        # AND the session file is updated correctly
        view_file = Path(td) / ".aico" / "sessions" / "main.json"
        view_data = json.loads(view_file.read_text())
        assert sorted(view_data["context_files"]) == ["file2.py"]


def test_drop_file_not_in_context_fails(tmp_path: Path) -> None:
    # GIVEN a session with one file in context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])
        (Path(td) / "file1.py").touch()
        runner.invoke(app, ["add", "file1.py"])

        # WHEN `aico drop` is run on a file not in the context
        result = runner.invoke(app, ["drop", "not_in_context.py"])

        # THEN the command fails with a non-zero exit code
        assert result.exit_code == 1

        # AND an error is printed to stderr
        assert "Error: File not in context: not_in_context.py" in result.stderr

        # AND the session file remains unchanged
        view_file = Path(td) / ".aico" / "sessions" / "main.json"
        view_data = json.loads(view_file.read_text())
        assert view_data["context_files"] == ["file1.py"]


def test_drop_multiple_with_one_not_in_context_partially_fails(tmp_path: Path) -> None:
    # GIVEN a session with two files in context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])
        (Path(td) / "file1.py").touch()
        (Path(td) / "file2.py").touch()
        runner.invoke(app, ["add", "file1.py", "file2.py"])

        # WHEN `aico drop` is run with one valid and one invalid file
        result = runner.invoke(app, ["drop", "file1.py", "not_in_context.py"])

        # THEN the command fails with a non-zero exit code
        assert result.exit_code == 1

        # AND it reports the successful removal
        assert "Dropped file from context: file1.py" in result.stdout

        # AND it reports the error for the other file
        assert "Error: File not in context: not_in_context.py" in result.stderr

        # AND the session file is updated to remove the valid file
        view_file = Path(td) / ".aico" / "sessions" / "main.json"
        view_data = json.loads(view_file.read_text())
        assert sorted(view_data["context_files"]) == ["file2.py"]


def test_drop_autocompletion(tmp_path: Path) -> None:
    # GIVEN a session with several files in context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        # AND a session file is initialized with context files
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        view_file = Path(td) / ".aico" / "sessions" / "main.json"
        view_data = json.loads(view_file.read_text())
        view_data["context_files"] = [
            "src/main.py",
            "src/utils.py",
            "docs/README.md",
        ]
        view_file.write_text(json.dumps(view_data))

        # WHEN the completion function is called with various partial inputs
        # THEN it returns the correct list of matching files
        assert sorted(complete_files_in_context(None, [], "src/")) == [
            "src/main.py",
            "src/utils.py",
        ]
        assert complete_files_in_context(None, [], "docs/") == ["docs/README.md"]
        assert complete_files_in_context(None, [], "src/main") == ["src/main.py"]
        assert complete_files_in_context(None, [], "invalid") == []


def test_add_symlink_to_inside_success(tmp_path: Path) -> None:
    # GIVEN an initialized session and a target file
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        target = Path(td) / "target.py"
        target.write_text("print('hello')")

        sym = Path(td) / "sym.py"
        sym.symlink_to(target)

        # WHEN adding the symlink
        result = runner.invoke(app, ["add", "sym.py"])

        # THEN succeeds and adds the symlink path
        assert result.exit_code == 0
        assert "Added file to context: sym.py" in result.stdout

        # AND session contains the symlink relative path
        view_file = Path(td) / ".aico" / "sessions" / "main.json"
        view_data = json.loads(view_file.read_text())
        assert view_data["context_files"] == ["sym.py"]


def test_drop_symlink_success(tmp_path: Path) -> None:
    # GIVEN session with symlink in context
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        target = Path(td) / "target.py"
        target.write_text("content")
        sym = Path(td) / "sym.py"
        sym.symlink_to(target)
        runner.invoke(app, ["add", "sym.py"])

        # WHEN dropping the symlink path
        result = runner.invoke(app, ["drop", "sym.py"])

        # THEN succeeds
        assert result.exit_code == 0
        assert "Dropped file from context: sym.py" in result.stdout

        # AND removed from session
        view_file = Path(td) / ".aico" / "sessions" / "main.json"
        view_data = json.loads(view_file.read_text())
        assert view_data["context_files"] == []


def test_autocompletion_includes_symlinks(tmp_path: Path) -> None:
    # GIVEN session with symlinks and regular files
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        runner.invoke(app, ["init"])

        # Regular file
        regular = Path(td) / "regular.py"
        regular.touch()

        # Symlinks
        sym1 = Path(td) / "sym1.py"
        sym1.symlink_to("regular.py")
        sym2 = Path(td) / "src/sym2.py"
        sym2.parent.mkdir()
        sym2.symlink_to("../regular.py")

        runner.invoke(app, ["add", "regular.py", "sym1.py", "src/sym2.py"])

        # WHEN completion
        # THEN includes symlinks (from session JSON paths)
        assert sorted(complete_files_in_context(None, [], "sym")) == ["sym1.py"]
        assert sorted(complete_files_in_context(None, [], "src/")) == ["src/sym2.py"]
        assert sorted(complete_files_in_context(None, [], "")) == sorted(["regular.py", "src/sym2.py", "sym1.py"])

    # GIVEN a directory with no session file
    with runner.isolated_filesystem():
        # WHEN the completion function is called
        completions = complete_files_in_context(None, [], "any")
        # THEN it returns an empty list without erroring
        assert completions == []
