"""Load ShareGPT-style conversation traces (e.g. codex_swebenchpro.json).

Schema is the common ShareGPT format: a list of conversations, each a dict with
a single "conversations" key holding turns of {"from": role, "value": text}.
"""

from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Role(str, Enum):
    human = "human"
    gpt = "gpt"


class Message(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    role: Role = Field(alias="from")
    value: str


class Conversation(BaseModel):
    conversations: list[Message]


class CodexTraces(RootModel[list[Conversation]]):
    @classmethod
    def load(cls, path: str | Path) -> CodexTraces:
        return cls.model_validate_json(Path(path).read_bytes())

    def __iter__(self):
        return iter(self.root)

    def __len__(self) -> int:
        return len(self.root)

    def __getitem__(self, i: int) -> Conversation:
        return self.root[i]


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "codex_swebenchpro.json"
    traces = CodexTraces.load(path)
    turns = sum(len(c.conversations) for c in traces)
    print(f"{len(traces)} conversations, {turns} turns")
    first = traces[0].conversations[0]
    print("first turn:", first.role.value, "->", first.value[:60].replace("\n", " "))
