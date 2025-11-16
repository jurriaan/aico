from pydantic import TypeAdapter

from aico.core.session_persistence import get_persistence
from aico.lib.models import ContextFilesResponse


def dump_context() -> None:
    persistence = get_persistence()
    _, session_data = persistence.load()
    response = ContextFilesResponse(context_files=sorted(session_data.context_files))
    print(TypeAdapter(ContextFilesResponse).dump_json(response, indent=2).decode())
