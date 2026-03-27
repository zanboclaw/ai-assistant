from pydantic import BaseModel


class MemoryWriteRequest(BaseModel):
    title: str
    content: str
    memory_kind: str = "fact"

