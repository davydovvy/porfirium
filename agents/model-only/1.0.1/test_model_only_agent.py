from types import SimpleNamespace
from uuid import uuid4

import pytest

from model_only_agent import prompt_for, run


class Message:
    def __init__(self) -> None:
        self.deltas: list[str] = []
        self.message_id = uuid4()
        self.completed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: object) -> None:
        self.completed = True

    async def delta(self, content: str) -> None:
        self.deltas.append(content)


class Runtime:
    def __init__(self, content: str) -> None:
        self.run_input = None
        self.content = content
        self.output = Message()
        self.model_prompt = ""
        self.proposed = []

    async def connect(self) -> None:
        self.run_input = SimpleNamespace(value="hello")

    async def model(self, prompt: str, *, model: str):
        self.model_prompt = prompt
        assert model == "default"
        return SimpleNamespace(content=self.content)

    async def propose_result(self, message_ids):
        assert self.output.completed
        self.proposed.append(message_ids)

    def message(self) -> Message:
        return self.output


@pytest.mark.asyncio
async def test_calls_runtime_model_and_streams_bounded_chunks() -> None:
    runtime = Runtime("x" * 2501)

    await run(runtime)  # type: ignore[arg-type]

    assert runtime.proposed == [[runtime.output.message_id]]
    assert "User message:\nhello" in runtime.model_prompt
    assert [len(value) for value in runtime.output.deltas] == [1000, 1000, 501]


def test_serializes_structured_input_without_repr() -> None:
    assert prompt_for({"answer": "да"}).endswith('{"answer": "да"}')
