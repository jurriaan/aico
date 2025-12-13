# pyright: standard

import linecache
import os
import shlex
import subprocess
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from click.testing import Result
from gherkin.errors import CompositeParserException
from gherkin.parser import Parser
from gherkin.token_matcher_markdown import GherkinInMarkdownTokenMatcher
from pydantic import TypeAdapter
from pytest_bdd import exceptions, gherkin_parser, given, parsers, then, when
from pytest_mock import MockerFixture
from typer.testing import CliRunner

from aico.consts import SESSION_FILE_NAME
from aico.history_utils import find_message_pairs
from aico.historystore import HistoryRecord, HistoryStore, append_pair_to_view, load_view, save_view
from aico.historystore.pointer import load_pointer
from aico.llm.providers.base import NormalizedChunk
from aico.main import app
from aico.models import (
    AssistantChatMessage,
    Mode,
    SessionData,
    UserChatMessage,
)
from tests.helpers import save_session

SessionDataAdapter = TypeAdapter(SessionData)


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


# Parametrized fixture for testing both session types
@pytest.fixture(params=["shared"])
def session_type(request: pytest.FixtureRequest) -> str:
    """A parametrized fixture to provide the session type for testing."""
    return str(request.param)  # pyright: ignore[reportAny]


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize session_type for all feature tests."""
    if "session_type" in metafunc.fixturenames:
        metafunc.parametrize("session_type", ["shared"])


# Step definitions should be added below this line
@pytest.fixture
def runner(mocker: MockerFixture) -> CliRunner:
    # Default for runner is input terminal
    mocker.patch("aico.commands.edit.is_input_terminal", return_value=True)

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
def given_initialized_session(project_dir: Path, runner: CliRunner, model_name: str, session_type: str) -> None:
    if session_type == "shared":
        result = runner.invoke(app, ["init", "--model", model_name])
        assert result.exit_code == 0
    else:  # session_type == "legacy"
        session_file = project_dir / SESSION_FILE_NAME
        new_session = SessionData(model=model_name)
        save_session(session_file, new_session)

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
    assert result.exit_code == 0, f"aico add failed: {result.output}"


def _add_pair_to_history(
    project_dir: Path, session_type: str, user_content: str, assistant_content: str, model: str = "m"
) -> None:
    session_file = project_dir / SESSION_FILE_NAME
    if session_type == "shared":
        view_path = load_pointer(session_file)
        view = load_view(view_path)
        store = HistoryStore(project_dir / ".aico" / "history")
        u = HistoryRecord(role="user", content=user_content, mode=Mode.CONVERSATION, timestamp="t1")
        a = HistoryRecord(
            role="assistant", content=assistant_content, mode=Mode.CONVERSATION, model=model, timestamp="t1"
        )
        _ = append_pair_to_view(store, view, u, a)
        save_view(view_path, view)
    else:  # session_type == "legacy"
        session_data: SessionData = SessionDataAdapter.validate_json(session_file.read_text())
        session_data.chat_history.extend(
            [
                UserChatMessage(role="user", content=user_content, mode=Mode.CONVERSATION, timestamp="t1"),
                AssistantChatMessage(
                    role="assistant",
                    content=assistant_content,
                    mode=Mode.CONVERSATION,
                    timestamp="t1",
                    model=model,
                    duration_ms=1,
                ),
            ]
        )
        save_session(session_file, session_data)


@given("the chat history contains one user/assistant pair")
def given_history_with_one_pair(project_dir: Path, session_type: str) -> None:
    _add_pair_to_history(project_dir, session_type, "default prompt", "assistant response")


@given(
    parsers.parse('the chat history contains one user/assistant pair where the assistant response is "{response_text}"')
)
def given_history_with_one_pair_specific_response(project_dir: Path, session_type: str, response_text: str) -> None:
    _add_pair_to_history(project_dir, session_type, "default user prompt", response_text)


@given(
    parsers.parse(
        'the chat history contains one user/assistant pair with content "{user_prompt}" and "{assistant_response}"'
    )
)
def given_history_with_specific_content(
    project_dir: Path, session_type: str, user_prompt: str, assistant_response: str
) -> None:
    _add_pair_to_history(project_dir, session_type, user_prompt, assistant_response)


@given(parsers.parse("for this scenario, the LLM will stream the response:"))
def given_llm_will_stream_response(mocker: MockerFixture, docstring: str) -> None:
    mock_provider = mocker.MagicMock()
    mock_client = mocker.MagicMock()
    mock_provider.configure_request.return_value = (mock_client, "test-model", {})
    mocker.patch("aico.llm.executor.get_provider_for_model", return_value=(mock_provider, "test-model"))

    def mock_process_chunk(chunk):
        return NormalizedChunk(content=chunk.choices[0].delta.content if chunk.choices else None)

    mock_provider.process_chunk.side_effect = mock_process_chunk

    def response_generator() -> Generator[Any, None, None]:
        chunk_size = 10
        response_text = docstring
        for i in range(0, len(response_text), chunk_size):
            chunk_content = response_text[i : i + chunk_size]

            # Build a mock structure that mimics OpenAI ChatCompletionChunk
            delta = mocker.MagicMock()
            delta.content = chunk_content

            choice = mocker.MagicMock()
            choice.delta = delta

            chunk = mocker.MagicMock()
            chunk.choices = [choice]
            chunk.usage = None

            yield chunk

    mock_client.chat.completions.create.return_value = response_generator()


@given("for this scenario, the token counter will report pre-defined counts")
def given_mocked_token_counts(mocker: MockerFixture) -> None:
    # Mock the centralized token counting helper used by `status`
    mock_token_counter = mocker.patch("aico.llm.tokens.count_tokens_for_messages")
    mock_token_counter.side_effect = [
        100,  # system prompt
        40,  # alignment prompt 1
        50,  # alignment prompt 2
        75,  # chat history
        200,  # CONVENTIONS.md
    ]


@given(parsers.parse('the model "{model_name}" has a known cost per token'))
def given_model_has_cost(mocker: MockerFixture, model_name: str) -> None:
    # Mock the component cost calculator in utils to return simple predictable costs
    # Mock the component cost calculator in utils
    _ = mocker.patch(
        "aico.llm.tokens.compute_component_cost",
        side_effect=lambda model, prompt_tokens, completion_tokens=0: float(prompt_tokens + completion_tokens) * 0.0001,
    )

    # Also mock get_model_info to return a ModelInfo with max_input_tokens
    # and default costs so that the status bar (Context Window) and costs render.
    from aico.model_registry import ModelInfo

    def fake_get_model_info(model_id: str) -> ModelInfo:
        if model_id == "test-model-with-cost":
            return ModelInfo(max_input_tokens=8192, input_cost_per_token=0.0001, output_cost_per_token=0.0001)
        return ModelInfo()

    _ = mocker.patch("aico.model_registry.get_model_info", side_effect=fake_get_model_info)
    _ = mocker.patch("aico.commands.status.get_model_info", side_effect=fake_get_model_info)


# WHEN steps


@given(parsers.parse('a test helper script named "{script_name}" exists'))
def given_test_helper_script_exists(project_dir: Path, script_name: str) -> None:
    script_path = project_dir / script_name
    script_content = '#!/bin/sh\n# A non-interactive \'editor\' for testing purposes.\necho -n "$NEW_CONTENT" > "$1"\n'
    _ = script_path.write_text(script_content)
    # Make the script executable
    # Add execute permissions for user, group, and others
    script_path.chmod(script_path.stat().st_mode | 0o111)


# WHEN steps


@when(parsers.parse("I run the command `{command}`"), target_fixture="command_result")
def when_run_command(
    runner: CliRunner, command: str, project_dir: Path, session_type: str, mocker: MockerFixture
) -> dict[str, Result]:
    # Check for pipe
    if " | " in command:
        mocker.patch("aico.commands.edit.is_input_terminal", return_value=False)
        left_cmd, right_cmd = command.split(" | ", 1)
        left_args = shlex.split(left_cmd)
        if left_args[0] == "aico":
            left_args = left_args[1:]

        right_args = shlex.split(right_cmd)

        left_result = runner.invoke(app, left_args, env={"COLUMNS": "120"}, catch_exceptions=False)
        assert left_result.exit_code == 0, f"Left side of pipe failed:\n{left_result.stdout}\n{left_result.stderr}"

        proc = subprocess.run(
            right_args, input=left_result.stdout, capture_output=True, text=True, check=False, cwd=project_dir
        )
        # Create a Click `Result` object from the subprocess output.
        result = Result(
            runner=runner,
            output_bytes=proc.stdout.encode(),
            stdout_bytes=proc.stdout.encode(),
            stderr_bytes=proc.stderr.encode(),
            exit_code=proc.returncode,
            exception=None,
            return_value=proc.returncode,
        )
        return {"result": result}

    # No pipe, simple command
    args = shlex.split(command)
    if args and args[0] == "aico":
        args = args[1:]

    # Special-case: In legacy mode, emulate `aico init` by creating a legacy session file
    if session_type == "legacy" and args and args[0] == "init":
        # Parse optional --model/-m argument
        model_value: str | None = None
        i = 1
        while i < len(args):
            if args[i] in ("--model", "-m") and i + 1 < len(args):
                model_value = args[i + 1]
                i += 2
            else:
                i += 1
        if model_value is None:
            model_value = "openrouter/google/gemini-2.5-pro"

        session_path = project_dir / SESSION_FILE_NAME
        new_session = SessionData(model=model_value)
        save_session(session_path, new_session)
        out = f"Initialized session file: {session_path}\n"
        result = Result(
            runner=runner,
            output_bytes=out.encode(),
            stdout_bytes=out.encode(),
            stderr_bytes=b"",
            exit_code=0,
            exception=None,
            return_value=0,
        )
        return {"result": result}

    result = runner.invoke(app, args, env={"COLUMNS": "120"}, catch_exceptions=False)
    return {"result": result}


@when(parsers.parse("I run the command:"), target_fixture="command_result")
def when_run_command_from_docstring(runner: CliRunner, docstring: str) -> dict[str, Result]:
    command_str = docstring.strip()
    args = shlex.split(command_str)

    env: dict[str, str] = {}
    while args and "=" in args[0]:
        key, value = args.pop(0).split("=", 1)
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        env[key] = value

    if args and args[0] == "aico":
        args = args[1:]

    result = runner.invoke(app, args, env={**os.environ, **env, "COLUMNS": "120"}, catch_exceptions=False)
    return {"result": result}


# THEN steps


# THEN steps


@then("the command should succeed")
def then_command_succeeds(command_result: dict[str, Result]) -> None:
    result = command_result["result"]
    assert result.exit_code == 0, f"Command failed unexpectedly:\n{result.stdout}\n{result.stderr}"


@then('a file named ".ai_session.json" should be created')
def then_session_file_created(project_dir: Path) -> None:
    assert (project_dir / SESSION_FILE_NAME).is_file()


def _get_current_context_files(project_dir: Path, session_type: str) -> list[str]:
    session_file = project_dir / SESSION_FILE_NAME
    if session_type == "shared":
        view_path = load_pointer(session_file)
        view = load_view(view_path)
        return view.context_files
    else:  # session_type == "legacy"
        session_data: SessionData = SessionDataAdapter.validate_json(session_file.read_text())
        return session_data.context_files


@then("the session context should be empty")
def then_context_is_empty(project_dir: Path, session_type: str) -> None:
    context_files = _get_current_context_files(project_dir, session_type)
    assert context_files == []


@then(parsers.parse('the session context should contain the file "{filename}"'))
def then_context_contains(project_dir: Path, session_type: str, filename: str) -> None:
    context_files = _get_current_context_files(project_dir, session_type)
    assert filename in context_files


@then(parsers.parse('the session context should not contain the file "{filename}"'))
def then_context_does_not_contain(project_dir: Path, session_type: str, filename: str) -> None:
    context_files = _get_current_context_files(project_dir, session_type)
    assert filename not in context_files


@then(parsers.parse("the session history should contain {count:d} user/assistant pair"))
@then(parsers.parse("the session history should contain {count:d} user/assistant pairs"))
def then_history_contains_pairs(project_dir: Path, session_type: str, count: int) -> None:
    session_file = project_dir / SESSION_FILE_NAME

    if session_type == "shared":
        from aico.historystore import find_message_pairs_in_view

        view_path = load_pointer(session_file)
        view = load_view(view_path)
        store = HistoryStore(project_dir / ".aico" / "history")
        pairs = find_message_pairs_in_view(store, view)
    else:  # session_type == "legacy"
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

    expected_content = docstring if docstring.endswith("\n") else docstring + "\n"

    assert actual_content == expected_content, (
        f"Content of '{filename}' did not match.\n"
        f"--- EXPECTED ---\n{expected_content}\n"
        f"--- ACTUAL ---\n{actual_content}\n"
        "--- END OF DIFF ---"
    )


@then(parsers.parse('the content of the assistant response at pair index {pair_index:d} should now be "{new_content}"'))
def then_response_content_is_updated(project_dir: Path, session_type: str, pair_index: int, new_content: str) -> None:
    session_file = project_dir / SESSION_FILE_NAME
    if session_type == "shared":
        from aico.historystore import find_message_pairs_in_view

        view_path = load_pointer(session_file)
        view = load_view(view_path)
        store = HistoryStore(project_dir / ".aico" / "history")
        pairs_positions = find_message_pairs_in_view(store, view)
        assistant_pos = pairs_positions[pair_index][1]
        assistant_index = view.message_indices[assistant_pos]
        assistant_record = store.read_many([assistant_index])[0]
        assert assistant_record.content == new_content
    else:  # session_type == "legacy"
        session_data: SessionData = SessionDataAdapter.validate_json(session_file.read_text())
        pairs = find_message_pairs(session_data.chat_history)
        assert len(pairs) > pair_index, f"Not enough pairs in history to check index {pair_index}"

        pair = pairs[pair_index]
        assistant_message = session_data.chat_history[pair.assistant_index]
        assert isinstance(assistant_message, AssistantChatMessage)
        assert assistant_message.content == new_content
