from types import SimpleNamespace

import pytest

from planning_assistant import MAX_INPUT_BYTES, answer_prompt, bounded_text, chunks, run


class Message:
    def __init__(self) -> None:
        self.deltas: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def delta(self, content: str) -> None:
        self.deltas.append(content)


class Runtime:
    def __init__(self, responses: list[str]) -> None:
        self.run_input = None
        self.responses = iter(responses)
        self.calls: list[tuple[str, str, int]] = []
        self.output = Message()
        self.cancelled = SimpleNamespace(is_set=lambda: False)

    async def connect(self) -> None:
        self.run_input = SimpleNamespace(value={"request": "prepare launch"})

    async def model(self, prompt: str, *, model: str, max_output_tokens: int):
        self.calls.append((prompt, model, max_output_tokens))
        return SimpleNamespace(content=next(self.responses))

    def message(self) -> Message:
        return self.output


@pytest.mark.asyncio
async def test_plans_then_answers_and_streams_utf8_bounded_chunks() -> None:
    runtime = Runtime(["check dependencies", "я" * 3000])

    await run(runtime)  # type: ignore[arg-type]

    assert len(runtime.calls) == 2
    assert "prepare launch" in runtime.calls[0][0]
    assert "check dependencies" in runtime.calls[1][0]
    assert runtime.calls[0][2] == 768
    assert runtime.calls[1][2] == 3072
    assert all(len(value.encode()) <= 4096 for value in runtime.output.deltas)
    assert "".join(runtime.output.deltas) == "я" * 3000


def test_bounded_text_serializes_and_truncates_on_utf8_boundary() -> None:
    assert bounded_text({"answer": "да"}) == '{"answer": "да"}'
    result = bounded_text("я" * MAX_INPUT_BYTES)
    assert result.endswith("[Input truncated]")
    assert len(result.removesuffix("\n[Input truncated]").encode()) <= MAX_INPUT_BYTES


def test_answer_prompt_does_not_claim_tool_access() -> None:
    prompt = answer_prompt("deploy", "verify first")
    assert "verify first" in prompt
    assert "must not claim to have used any" in prompt


def test_chunks_rejects_no_valid_utf8_boundary() -> None:
    assert list(chunks("abc", maximum=2)) == ["ab", "c"]
