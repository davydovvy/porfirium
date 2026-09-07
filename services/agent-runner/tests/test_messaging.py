import asyncio
from types import SimpleNamespace

from agent_runner.messaging import consume_admissions


class Message:
    data = b"not-json"
    subject = "porfirium.run.command.requested"

    def __init__(self, deliveries: int) -> None:
        self.metadata = SimpleNamespace(num_delivered=deliveries)
        self.acked = False
        self.naks: list[int] = []

    async def ack(self) -> None:
        self.acked = True

    async def nak(self, delay: int) -> None:
        self.naks.append(delay)


class Subscription:
    def __init__(self, message: Message) -> None:
        self.messages = self
        self.message = message

    def __aiter__(self) -> "Subscription":
        return self

    async def __anext__(self) -> Message:
        if self.message is None:
            raise StopAsyncIteration
        message, self.message = self.message, None
        return message


def test_consumer_retries_below_delivery_limit() -> None:
    message = Message(4)
    app = SimpleNamespace(state=SimpleNamespace())
    asyncio.run(consume_admissions(app, Subscription(message), object(), max_deliveries=5))
    assert message.naks == [1]
    assert not message.acked


def test_consumer_dead_letters_and_acks_at_delivery_limit(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    async def fake_dead_letter(*args: object, **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("agent_runner.messaging.dead_letter", fake_dead_letter)
    message = Message(5)
    app = SimpleNamespace(state=SimpleNamespace(pool=object()))
    asyncio.run(consume_admissions(app, Subscription(message), object(), max_deliveries=5))
    assert message.acked
    assert not message.naks
    assert calls[0]["consumer"] == "agent-runner-admission-v1"
