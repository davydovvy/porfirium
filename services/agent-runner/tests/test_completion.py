import asyncio
from uuid import uuid4


def test_completion_reconciliation_reads_postgres_json_confirmation() -> None:
    import json

    from agent_runner.completion import _converge

    message_id = uuid4()
    run_id = uuid4()

    class Connection:
        def __init__(self):
            self.confirmed = False

        async def fetchrow(self, query, *args):
            if query.startswith("SELECT * FROM run_completion"):
                return {"final_message_ids": [message_id]}
            return None

        async def fetch(self, query, *args):
            return [{"confirmation": "messages", "payload": json.dumps({
                "message_ids": [str(message_id)],
            })}]

        async def execute(self, query, *args):
            assert "messages_confirmed=true" in query
            assert args == (run_id,)
            self.confirmed = True

    connection = Connection()
    asyncio.run(_converge(connection, run_id))
    assert connection.confirmed
