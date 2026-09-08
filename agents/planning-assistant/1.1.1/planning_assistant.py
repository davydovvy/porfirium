from __future__ import annotations

import asyncio
import json

from porfirium_agent_sdk import RuntimeClient


def bounded(value: object, maximum: int = 6 * 1024) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if not text.strip():
        raise ValueError("run input is empty")
    return text.encode()[:maximum].decode("utf-8", errors="ignore")


def chunks(value: str, maximum: int = 4096):
    current = ""
    size = 0
    for character in value:
        encoded_size = len(character.encode())
        if current and size + encoded_size > maximum:
            yield current
            current, size = "", 0
        current += character
        size += encoded_size
    if current:
        yield current


async def run(runtime: RuntimeClient) -> None:
    await runtime.connect()
    if runtime.run_input is None:
        raise ValueError("run input is missing")
    current_time = await runtime.tool(
        "time_get_current_time", {"timezone": "UTC"}
    )
    if current_time.is_error:
        raise RuntimeError("current-time tool failed")
    prompt = (
        "Answer the user's request clearly. Use the trusted current-time result when relevant, "
        "but do not claim access to any other tools.\n\nCurrent time result:\n"
        + bounded(current_time.result, 3 * 1024)
        + "\n\nUser request:\n"
        + bounded(runtime.run_input.value)
    )
    response = await runtime.model(prompt, model="default", max_output_tokens=3072)
    async with runtime.message() as message:
        for chunk in chunks(response.content):
            await message.delta(chunk)

    await runtime.propose_result([message.message_id])


async def main() -> None:
    runtime = RuntimeClient.from_environment()
    try:
        await run(runtime)
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
