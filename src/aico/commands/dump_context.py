import json

from aico.core.session_loader import load_active_session
from aico.lib.models import ContextFilesResponse


def dump_context() -> None:
    session = load_active_session()
    response = ContextFilesResponse(context_files=sorted(session.data.context_files))
    print(json.dumps(response, indent=2))
