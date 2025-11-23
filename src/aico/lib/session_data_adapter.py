from pydantic import TypeAdapter

from aico.lib.models import SessionData

SessionDataAdapter = TypeAdapter(SessionData)
