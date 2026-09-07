from __future__ import annotations

import asyncio
import json

from porfirium_agent_sdk import RuntimeClient

INSTRUCTIONS = (
    "You are Porfirium's model-only assistant. Answer the user's message clearly and directly. "
    "You have no tools and must not claim to have used any."
)


def prompt_for(value: object) -> str:
    user_input = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if not user_input.strip():
        raise ValueError("run input is empty")
    return f"{INSTRUCTIONS}\n\nUser message:\n{user_input}"


async def run(runtime: RuntimeClient) -> None:
    await runtime.connect()
    if runtime.run_input is None:
        raise ValueError("run input is missing")
    response = await runtime.model(prompt_for(runtime.run_input.value), model="default")
    async with runtime.message() as message:
        for offset in range(0, len(response.content), 1000):
            await message.delta(response.content[offset:offset + 1000])


async def main() -> None:
    runtime = RuntimeClient.from_environment()
    try:
        await run(runtime)
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
