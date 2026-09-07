from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

from agent_runner.completion import consume_run_event
from agent_runner.models import RunAdmission
from agent_runner.outbox import publish_pending

logger = logging.getLogger(__name__)


async def consume_completion_events(runner: Any, subscription: Any) -> None:
    async for message in subscription.messages:
        try:
            envelope = json.loads(message.data)
            supported = {
                "porfirium.run.result_proposed.v1",
                "porfirium.run.messages_committed.v1",
                "porfirium.run.checkpoint_committed.v1",
                "porfirium.message.started.v1",
                "porfirium.run.suspension_committed.v1",
            }
            if envelope.get("type") in supported:
                if envelope.get("type") == "porfirium.run.suspension_committed.v1":
                    await runner.suspend(envelope)
                else:
                    await consume_run_event(runner.pool, envelope)
        except Exception:
            logger.exception("run completion event failed; message will be retried")
            await message.nak(delay=1)
        else:
            await message.ack()


async def consume_admissions(app: Any, subscription: Any) -> None:
    async for message in subscription.messages:
        try:
            envelope = json.loads(message.data)
            if not isinstance(envelope, dict):
                logger.error("discarding malformed run admission: JSON root is not an object")
                await message.ack()
                continue
            admission = RunAdmission.model_validate(
                {
                    key: envelope.get(key)
                    for key in RunAdmission.model_fields
                }
            )
            idempotency_key = str(envelope["id"])
            specification = await app.state.registry.resolve(admission, idempotency_key)
            app.state.verify_specification(specification)
            await app.state.runner.admit(admission, idempotency_key, specification)
        except Exception:
            logger.exception("run admission failed; message will be retried")
            await message.nak(delay=1)
        else:
            await message.ack()


async def publish_loop(pool: Any, jetstream: Any) -> None:
    while True:
        with suppress(Exception):
            await publish_pending(pool, jetstream)
        await asyncio.sleep(0.05)
