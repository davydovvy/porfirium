from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator

from porfirium_agent_sdk import RuntimeClient

MAX_INPUT_BYTES = 6 * 1024
MAX_DELTA_BYTES = 4096


def bounded_text(value: object, maximum: int = MAX_INPUT_BYTES) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if not text.strip():
        raise ValueError("run input is empty")
    encoded = text.encode("utf-8")
    if len(encoded) <= maximum:
        return text
    return encoded[:maximum].decode("utf-8", errors="ignore") + "\n[Input truncated]"


def chunks(value: str, maximum: int = MAX_DELTA_BYTES) -> Iterator[str]:
    chunk = ""
    chunk_bytes = 0
    for character in value:
        size = len(character.encode("utf-8"))
        if chunk and chunk_bytes + size > maximum:
            yield chunk
            chunk = ""
            chunk_bytes = 0
        chunk += character
        chunk_bytes += size
    if chunk:
        yield chunk


def planning_prompt(user_input: str) -> str:
    return (
        "Create a concise internal plan for answering the request below. Identify assumptions and "
        "important constraints. Do not address the user yet.\n\nRequest:\n" + user_input
    )


def answer_prompt(user_input: str, plan: str) -> str:
    return (
        "You are Porfirium's planning assistant. Answer the request clearly and directly, using "
        "the internal plan below. You have no tools and must not claim to have used any. Do not "
        "reproduce or mention the internal plan.\n\nInternal plan:\n"
        + plan
        + "\n\nRequest:\n"
        + user_input
    )


async def run(runtime: RuntimeClient) -> None:
    await runtime.connect()
    if runtime.run_input is None:
        raise ValueError("run input is missing")
    user_input = bounded_text(runtime.run_input.value)
    plan = await runtime.model(
        planning_prompt(user_input), model="default", max_output_tokens=768
    )
    if runtime.cancelled.is_set():
        return
    response = await runtime.model(
        answer_prompt(user_input, bounded_text(plan.content, maximum=4 * 1024)),
        model="default",
        max_output_tokens=3072,
    )
    if runtime.cancelled.is_set():
        return
    async with runtime.message() as message:
        for chunk in chunks(response.content):
            await message.delta(chunk)


async def main() -> None:
    runtime = RuntimeClient.from_environment()
    try:
        await run(runtime)
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
