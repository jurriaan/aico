import typer

from aico.exceptions import InvalidInputError
from aico.historystore import SessionView, save_view, switch_active_pointer
from aico.session import Session


def session_new(
    name: str,
    model: str | None,
) -> None:
    if not name.strip():
        raise InvalidInputError("New session name is required.")

    session = Session.load_active()
    new_view_path = session.get_view_path(name)

    if new_view_path.exists():
        raise InvalidInputError(f"A session view named '{name}' already exists.")

    new_model = model or session.data.model

    view = SessionView(model=new_model, context_files=[], message_indices=[], history_start_pair=0, excluded_pairs=[])
    save_view(new_view_path, view)
    switch_active_pointer(session.file_path, new_view_path)

    typer.echo(f"Created new empty session '{name}' with model '{new_model}' and switched to it.")
