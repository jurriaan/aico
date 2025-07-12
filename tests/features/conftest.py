import linecache
import shlex
import subprocess
from collections.abc import Generator
from pathlib import Path
from unittest import mock

import pytest
from click.testing import Result
from gherkin.errors import CompositeParserException
from gherkin.parser import Parser
from gherkin.token_matcher_markdown import GherkinInMarkdownTokenMatcher
from pytest_bdd import exceptions, gherkin_parser, given, parsers, then, when
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.index_logic import find_message_pairs
from aico.main import app
from aico.models import (
    AssistantChatMessage,
    LiteLLMChoiceContainer,
    LiteLLMDelta,
    LiteLLMStreamChoice,
    Mode,
    SessionData,
    UserChatMessage,
)
from aico.utils import SESSION_FILE_NAME, SessionDataAdapter, save_session


# This file is used to override the default `get_gherkin_document` function so that
# it can handle parsing Gherkin documents in Markdown format.
def new_get_gherkin_document(abs_filename: str, encoding: str = "utf-8") -> gherkin_parser.GherkinDocument:
    with open(abs_filename, encoding=encoding) as f:
        feature_file_text = f.read()

    try:
        gherkin_data = Parser().parse(feature_file_text, GherkinInMarkdownTokenMatcher())
    except CompositeParserException as e:
        message = f"{e.args[0]}"
        line = e.errors[0].location["line"]
        line_content = linecache.getline(abs_filename, e.errors[0].location["line"]).rstrip("\n")
        filename = abs_filename
        gherkin_parser.handle_gherkin_parser_error(message, line, line_content, filename, e)
        # If no patterns matched, raise a generic GherkinParserError
        raise exceptions.GherkinParseError(f"Unknown parsing error: {message}", line, line_content, filename) from e

    # At this point, the `gherkin_data` should be valid if no exception was raised
    return gherkin_parser.GherkinDocument.from_dict(dict(gherkin_data))


_ = mock.patch("pytest_bdd.parser.get_gherkin_document", new=new_get_gherkin_document).start()


# Step definitions should be added below this line
@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project_dir(runner: CliRunner, tmp_path: Path) -> Generator[Path]:
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        yield Path(td)


@pytest.fixture
def command_result() -> dict[str, Result]:
    """A carrier for the last command result."""
    return {}


@pytest.fixture
def docstring() -> str | None:
    return None


# GIVEN steps


@given("I am in a new project directory without an existing session")
def given_project_dir_exists(project_dir: Path) -> None:
    """This step just ensures the project_dir fixture is initialized."""
    assert project_dir.is_dir()


@given(parsers.parse('a file named "{filename}" exists'))
def given_file_exists(project_dir: Path, filename: str) -> None:
    _ = (project_dir / filename).write_text(f"Content of {filename}")


@given(parsers.parse('a project with an initialized aico session for model "{model_name}"'))
def given_initialized_session(project_dir: Path, runner: CliRunner, model_name: str) -> None:
    result = runner.invoke(app, ["init", "--model", model_name])
    assert result.exit_code == 0
    assert (project_dir / SESSION_FILE_NAME).is_file()


@given(parsers.parse('the file "{filename}" is in the session context'))
@given(parsers.parse('the file "{filename}" is in the session context:'))
def given_file_in_context(project_dir: Path, runner: CliRunner, filename: str, docstring: str | None) -> None:
    file = project_dir / filename
    if not file.is_file() or docstring is not None:
        docstring = docstring or f"Content of {filename}"
        contents = docstring if docstring.endswith("\n") else docstring + "\n"
        _ = file.write_text(contents)
    result = runner.invoke(app, ["add", filename])
    assert result.exit_code == 0


@given("the chat history contains one user/assistant pair")
def given_history_with_one_pair(project_dir: Path) -> None:
    session_file = project_dir / SESSION_FILE_NAME
    session_data: SessionData = SessionDataAdapter.validate_json(session_file.read_text())
    session_data.chat_history.extend(
        [
            UserChatMessage(role="user", content="p1", mode=Mode.CONVERSATION, timestamp="t1"),
            AssistantChatMessage(
                role="assistant", content="a1", mode=Mode.CONVERSATION, timestamp="t1", model="m", duration_ms=1
            ),
        ]
    )
    save_session(session_file, session_data)


@given(parsers.parse("for this scenario, the LLM will stream the response:"))
def given_llm_will_stream_response(mocker: MockerFixture, docstring: str) -> None:
    mock_completion = mocker.patch("litellm.completion", autospec=True)

    def response_generator() -> Generator[LiteLLMChoiceContainer, None, None]:
        chunk_size = 10
        response_text = docstring
        for i in range(0, len(response_text), chunk_size):
            chunk_content = response_text[i : i + chunk_size]
            delta = mocker.MagicMock(spec=LiteLLMDelta)
            delta.content = chunk_content
            choice = mocker.MagicMock(spec=LiteLLMStreamChoice)
            choice.delta = delta
            container = mocker.MagicMock(spec=LiteLLMChoiceContainer)
            container.choices = [choice]
            container.model = "test-model-response"
            yield container

    mock_completion.return_value = response_generator()
    # Mock cost calculation, which happens after generation
    _ = mocker.patch("litellm.completion_cost", return_value=0.01)


@given("for this scenario, the token counter will report pre-defined counts")
def given_mocked_token_counts(mocker: MockerFixture) -> None:
    # Based on the scenario description for the token breakdown, we mock the side effects
    # of `litellm.token_counter` in the order it's called in `commands/status.py`.
    mock_token_counter = mocker.patch("aico.commands.status._count_tokens")
    mock_token_counter.side_effect = [
        100,  # system prompt
        40,  # alignment prompt 1
        50,  # alignment prompt 2
        75,  # chat history
        200,  # CONVENTIONS.md
    ]


@given(parsers.parse('the model "{model_name}" has a known cost per token'))
def given_model_has_cost(mocker: MockerFixture, model_name: str) -> None:  # pyright: ignore[reportUnusedParameter]
    # This step mocks both cost calculation and model info retrieval
    mock_cost = mocker.patch(
        "litellm.completion_cost",
        # Use a simple, predictable cost for testing
        side_effect=lambda completion_response: float(completion_response["usage"]["prompt_tokens"]) * 0.0001,  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    )
    mock_model_info = mocker.patch(
        "litellm.get_model_info", return_value={"max_input_tokens": 8192, "input_cost_per_token": 0.0001}
    )

    # Make these mocks available to the test case context
    mocker.patch.dict(
        "sys.modules",
        {
            "litellm": mocker.MagicMock(
                completion_cost=mock_cost,
                get_model_info=mock_model_info,
            )
        },
    )


# WHEN steps


@when(parsers.parse("I run the command `{command}`"), target_fixture="command_result")
def when_run_command(runner: CliRunner, command: str, project_dir: Path) -> dict[str, Result]:
    if " | " in command:
        left_cmd, right_cmd = command.split(" | ", 1)
        left_args = shlex.split(left_cmd)[1:]
        right_args = shlex.split(right_cmd)

        left_result = runner.invoke(app, left_args, env={"COLUMNS": "120"})
        assert left_result.exit_code == 0, f"Left side of pipe failed:\n{left_result.stderr}"

        # Run right command with stdin from left command's stdout
        proc = subprocess.run(
            right_args,
            input=left_result.stdout,
            capture_output=True,
            text=True,
            check=False,
            cwd=project_dir,
        )

        # Create a Click `Result` object from the subprocess output to ensure
        # compatibility with subsequent `then` steps.
        result = Result(
            runner=runner,
            stdout_bytes=proc.stdout.encode("utf-8"),
            stderr_bytes=proc.stderr.encode("utf-8"),
            output_bytes=proc.stdout.encode("utf-8"),
            exception=None,
            return_value=proc.returncode,
            exit_code=proc.returncode,
            exc_info=None,
        )
        return {"result": result}

    args = shlex.split(command)
    result = runner.invoke(app, args[1:], env={"COLUMNS": "120"})
    return {"result": result}


# THEN steps


@then("the command should succeed")
def then_command_succeeds(command_result: dict[str, Result]) -> None:
    result = command_result["result"]
    assert result.exit_code == 0, result.stderr


@then('a file named ".ai_session.json" should be created')
def then_session_file_created(project_dir: Path) -> None:
    assert (project_dir / SESSION_FILE_NAME).is_file()


def _get_current_context_files(project_dir: Path) -> list[str]:
    session_file = project_dir / SESSION_FILE_NAME
    session_data: SessionData = SessionDataAdapter.validate_json(session_file.read_text())
    return session_data.context_files


@then("the session context should be empty")
def then_context_is_empty(project_dir: Path) -> None:
    context_files = _get_current_context_files(project_dir)
    assert context_files == []


@then(parsers.parse('the session context should contain the file "{filename}"'))
def then_context_contains(project_dir: Path, filename: str) -> None:
    context_files = _get_current_context_files(project_dir)
    assert filename in context_files


@then(parsers.parse('the session context should not contain the file "{filename}"'))
def then_context_does_not_contain(project_dir: Path, filename: str) -> None:
    context_files = _get_current_context_files(project_dir)
    assert filename not in context_files


@then(parsers.parse("the session history should contain {count:d} user/assistant pair"))
@then(parsers.parse("the session history should contain {count:d} user/assistant pairs"))
def then_history_contains_pairs(project_dir: Path, count: int) -> None:
    session_file = project_dir / SESSION_FILE_NAME
    session_data: SessionData = SessionDataAdapter.validate_json(session_file.read_text())
    pairs = find_message_pairs(session_data.chat_history)
    assert len(pairs) == count, f"Expected {count} pairs, but found {len(pairs)}"


@then(parsers.parse("the output should be:"))
def then_output_is(command_result: dict[str, Result], docstring: str) -> None:
    actual_output = "\n".join(line.rstrip() for line in command_result["result"].output.splitlines(keepends=False))
    expected_output = docstring.strip()
    assert actual_output == expected_output, (
        "Actual output did not match expected output.\n"
        f"--- EXPECTED ---\n{expected_output}\n\n"
        f"--- ACTUAL ---\n{actual_output}\n"
        "--- END OF DIFF ---"
    )
    then_command_succeeds(command_result)


@then(parsers.parse('the file "{filename}" should contain:'))
def then_file_should_contain(project_dir: Path, filename: str, docstring: str) -> None:
    file_path = project_dir / filename
    assert file_path.is_file(), f"File '{filename}' was not found in {project_dir}"
    actual_content = file_path.read_text()

    # Docstrings from Gherkin are dedented.
    # The `given` step that creates files adds a newline. We must be consistent.
    expected_content = docstring if docstring.endswith("\n") else docstring + "\n"

    assert actual_content == expected_content, (
        f"Content of '{filename}' did not match.\n"
        f"--- EXPECTED ---\n{expected_content}\n"
        f"--- ACTUAL ---\n{actual_content}\n"
        "--- END OF DIFF ---"
    )
