from types import SimpleNamespace

import pytest

from planning_assistant import run


class Message:
    def __init__(self) -> None:
        self.deltas = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def delta(self, value):
        self.deltas.append(value)


class Runtime:
    def __init__(self) -> None:
        self.run_input = None
        self.output = Message()
        self.prompt = ""

    async def connect(self):
        self.run_input = SimpleNamespace(value="What time is it?")

    async def tool(self, name, arguments):
        assert name == "time_get_current_time"
        assert arguments == {"timezone": "UTC"}
        return SimpleNamespace(result={"timestamp": "2026-09-07T12:00:00+00:00"}, is_error=False)

    async def model(self, prompt, *, model, max_output_tokens):
        self.prompt = prompt
        assert model == "default"
        assert max_output_tokens == 3072
        return SimpleNamespace(content="It is 12:00 UTC.")

    def message(self):
        return self.output


@pytest.mark.asyncio
async def test_invokes_declared_time_tool_before_model_response() -> None:
    runtime = Runtime()

    await run(runtime)  # type: ignore[arg-type]

    assert "2026-09-07T12:00:00+00:00" in runtime.prompt
    assert runtime.output.deltas == ["It is 12:00 UTC."]
