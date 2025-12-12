from pydantic import TypeAdapter

from aico.models import SessionData

SessionDataAdapter = TypeAdapter(SessionData)
