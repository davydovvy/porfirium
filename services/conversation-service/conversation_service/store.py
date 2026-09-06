# ruff: noqa: E501

from __future__ import annotations

import hashlib
import os
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import asyncpg

from conversation_service.domain import (
    Conversation,
    InputRequest,
    Message,
    PresentationEvent,
    canonical_json,
    message_json,
    validate_completion,
)
from conversation_service.problems import ConversationProblem


class PostgresStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls) -> PostgresStore:
        return cls(await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=10))

    async def close(self) -> None:
        await self.pool.close()

    @staticmethod
    def conversation(row: asyncpg.Record) -> Conversation:
        return Conversation(**dict(row))

    @staticmethod
    def message(row: asyncpg.Record) -> Message:
        return Message(**dict(row))

    @staticmethod
    def input_request(row: asyncpg.Record) -> InputRequest:
        values = dict(row)
        values.pop("answered_at", None)
        return InputRequest(**values)

    async def _owned(
        self, executor: Any, owner_id: UUID, conversation_id: UUID, *, lock: bool = False
    ) -> asyncpg.Record:
        suffix = " FOR UPDATE" if lock else ""
        row = await executor.fetchrow(
            "SELECT * FROM conversations WHERE conversation_id=$1 AND owner_id=$2" + suffix,
            conversation_id,
            owner_id,
        )
        if not row:
            raise ConversationProblem(404, "conversation_not_found", "Conversation was not found")
        return row

    async def _present(
        self,
        connection: asyncpg.Connection,
        conversation_id: UUID,
        event_type: str,
        data: dict[str, Any],
    ) -> int:
        sequence = await connection.fetchval(
            "UPDATE conversations SET last_sequence=last_sequence+1,updated_at=now() WHERE conversation_id=$1 RETURNING last_sequence",
            conversation_id,
        )
        await connection.execute(
            "INSERT INTO presentation_events(conversation_id,sequence,event_type,data) VALUES($1,$2,$3,$4::jsonb)",
            conversation_id,
            sequence,
            event_type,
            canonical_json(data).decode(),
        )
        return int(sequence)

    async def create_conversation(
        self, owner_id: UUID, idempotency_key: str, payload: dict[str, Any]
    ) -> Conversation:
        digest = hashlib.sha256(canonical_json(payload)).hexdigest()
        operation = "create_conversation"
        async with self.pool.acquire() as connection, connection.transaction():
            old = await connection.fetchrow(
                "SELECT * FROM request_idempotency WHERE owner_id=$1 AND operation=$2 AND idempotency_key=$3 FOR UPDATE",
                owner_id,
                operation,
                idempotency_key,
            )
            if old:
                if old["request_sha256"] != digest:
                    raise ConversationProblem(
                        409, "idempotency_conflict", "Idempotency key was reused"
                    )
                return self.conversation(
                    await connection.fetchrow(
                        "SELECT * FROM conversations WHERE conversation_id=$1", old["resource_id"]
                    )
                )
            conversation_id = uuid4()
            row = await connection.fetchrow(
                "INSERT INTO conversations(conversation_id,owner_id,thread_id,release_id,configuration_revision_id,title) VALUES($1,$2,$3,$4,$5,$6) RETURNING *",
                conversation_id,
                owner_id,
                payload["thread_id"],
                payload["release_id"],
                payload["configuration_revision_id"],
                payload["title"],
            )
            await connection.execute(
                "INSERT INTO request_idempotency VALUES($1,$2,$3,$4,$5,NULL)",
                owner_id,
                operation,
                idempotency_key,
                digest,
                conversation_id,
            )
            return self.conversation(row)

    async def list_conversations(self, owner_id: UUID) -> list[Conversation]:
        return [
            self.conversation(row)
            for row in await self.pool.fetch(
                "SELECT * FROM conversations WHERE owner_id=$1 ORDER BY updated_at DESC", owner_id
            )
        ]

    async def projection(self, owner_id: UUID, conversation_id: UUID) -> dict[str, Any]:
        row = await self._owned(self.pool, owner_id, conversation_id)
        messages = [
            self.message(item)
            for item in await self.pool.fetch(
                "SELECT * FROM messages WHERE conversation_id=$1 ORDER BY created_at,message_id",
                conversation_id,
            )
        ]
        inputs = [
            self.input_request(item)
            for item in await self.pool.fetch(
                "SELECT * FROM input_requests WHERE conversation_id=$1 ORDER BY created_at,input_request_id",
                conversation_id,
            )
        ]
        return {
            "conversation": self.conversation(row),
            "messages": messages,
            "input_requests": inputs,
        }

    async def create_message(
        self, owner_id: UUID, conversation_id: UUID, idempotency_key: str, payload: dict[str, Any]
    ) -> tuple[Message, int]:
        digest = hashlib.sha256(canonical_json(payload)).hexdigest()
        operation = f"message:{conversation_id}"
        async with self.pool.acquire() as connection, connection.transaction():
            conversation = await self._owned(connection, owner_id, conversation_id, lock=True)
            old = await connection.fetchrow(
                "SELECT * FROM request_idempotency WHERE owner_id=$1 AND operation=$2 AND idempotency_key=$3 FOR UPDATE",
                owner_id,
                operation,
                idempotency_key,
            )
            if old:
                if old["request_sha256"] != digest:
                    raise ConversationProblem(
                        409, "idempotency_conflict", "Idempotency key was reused"
                    )
                row = await connection.fetchrow(
                    "SELECT * FROM messages WHERE message_id=$1", old["resource_id"]
                )
                return self.message(row), int(old["conversation_sequence"])
            try:
                row = await connection.fetchrow(
                    "INSERT INTO messages(message_id,conversation_id,run_id,role,status,content,completed_at) VALUES($1,$2,$3,'user','completed',$4,now()) RETURNING *",
                    payload["message_id"],
                    conversation_id,
                    payload["run_id"],
                    payload["content"],
                )
            except asyncpg.UniqueViolationError as exc:
                raise ConversationProblem(
                    409, "message_exists", "Message ID already exists"
                ) from exc
            message = self.message(row)
            await connection.execute(
                "UPDATE conversations SET delegation_grant_id=$2 WHERE conversation_id=$1",
                conversation_id, payload["delegation_grant_id"],
            )
            sequence = await self._present(
                connection, conversation_id, "message.completed", message_json(message)
            )
            event_id = uuid4()
            event = {
                "specversion": "1.0",
                "type": "porfirium.run.requested.v1",
                "id": str(event_id),
                "source": "conversation-service",
                "subject": f"conversation/{conversation_id}",
                "user_id": str(owner_id),
                "conversation_id": str(conversation_id),
                "thread_id": str(conversation["thread_id"]),
                "release_id": str(conversation["release_id"]),
                "run_id": str(payload["run_id"]),
                "message_id": str(payload["message_id"]),
                "delegation_grant_id": str(payload["delegation_grant_id"]),
                "configuration_revision_id": (
                    str(conversation["configuration_revision_id"])
                    if conversation["configuration_revision_id"] else None
                ),
                "starting_checkpoint_id": None,
                "trigger": {"type": "user_message", "id": str(payload["message_id"])},
                "trace_id": event_id.hex,
                "schema_version": 1,
            }
            await connection.execute(
                "INSERT INTO outbox_events(event_id,subject,payload) VALUES($1,'porfirium.run.command.requested',$2::jsonb)",
                event_id,
                canonical_json(event).decode(),
            )
            await connection.execute(
                "INSERT INTO request_idempotency VALUES($1,$2,$3,$4,$5,$6)",
                owner_id,
                operation,
                idempotency_key,
                digest,
                payload["message_id"],
                sequence,
            )
            return message, sequence

    async def replay(
        self, owner_id: UUID, conversation_id: UUID, after: int, limit: int = 1000
    ) -> list[PresentationEvent]:
        await self._owned(self.pool, owner_id, conversation_id)
        rows = await self.pool.fetch(
            "SELECT * FROM presentation_events WHERE conversation_id=$1 AND sequence>$2 ORDER BY sequence LIMIT $3",
            conversation_id,
            after,
            limit,
        )
        return [PresentationEvent(**dict(row)) for row in rows]

    async def project(self, envelope: dict[str, Any]) -> int | None:
        try:
            event_id = UUID(str(envelope["id"]))
            conversation_id = UUID(str(envelope["conversation_id"]))
            owner_id = UUID(str(envelope["user_id"]))
            run_id = UUID(str(envelope["run_id"]))
            data = envelope["data"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ConversationProblem(
                422, "event_invalid", "Runtime event envelope is invalid"
            ) from exc
        if envelope.get("schema_version") != 1:
            raise ConversationProblem(422, "event_invalid", "Runtime event envelope is invalid")
        async with self.pool.acquire() as connection, connection.transaction():
            if await connection.fetchval("SELECT 1 FROM inbox_events WHERE event_id=$1", event_id):
                return None
            await self._owned(connection, owner_id, conversation_id, lock=True)
            kind = str(envelope.get("type"))
            mid = UUID(str(data["message_id"])) if data.get("message_id") else None
            if kind == "porfirium.run.result_proposed.v1":
                message_ids = [UUID(str(value)) for value in data.get("final_message_ids", [])]
                if not message_ids or "messages" not in data.get("required_confirmations", []):
                    await connection.execute(
                        "INSERT INTO inbox_events(event_id,event_type) VALUES($1,$2)", event_id, kind
                    )
                    return None
                count = await connection.fetchval(
                    "SELECT count(*) FROM messages WHERE conversation_id=$1 AND run_id=$2 "
                    "AND message_id=ANY($3::uuid[]) AND status='completed'",
                    conversation_id, run_id, message_ids,
                )
                await connection.execute(
                    "INSERT INTO result_proposals(run_id,event_id,conversation_id,final_message_ids) "
                    "VALUES($1,$2,$3,$4) ON CONFLICT(run_id) DO NOTHING",
                    run_id, event_id, conversation_id, message_ids,
                )
                if count == len(message_ids):
                    await self._confirm_messages(connection, run_id, message_ids)
                sequence = await self._present(connection, conversation_id, kind, data)
                await connection.execute(
                    "INSERT INTO inbox_events(event_id,event_type) VALUES($1,$2)", event_id, kind
                )
                return sequence
            if kind == "porfirium.run.suspension_committed.v1":
                suspension_id = UUID(str(data["suspension_id"]))
                await connection.execute(
                    "INSERT INTO suspension_commitments(suspension_id,event_id,run_id,"
                    "checkpoint_id,input_request_id) VALUES($1,$2,$3,$4,$5) "
                    "ON CONFLICT(suspension_id) DO NOTHING",
                    suspension_id, event_id, run_id, UUID(str(data["checkpoint_id"])),
                    UUID(str(data["input_request_id"])),
                )
                commitment = await connection.fetchrow(
                    "SELECT * FROM suspension_commitments WHERE suspension_id=$1", suspension_id
                )
                if (
                    commitment["run_id"] != run_id
                    or commitment["checkpoint_id"] != UUID(str(data["checkpoint_id"]))
                    or commitment["input_request_id"] != UUID(str(data["input_request_id"]))
                ):
                    raise ConversationProblem(
                        409, "suspension_conflict", "Suspension identity conflicts"
                    )
                sequence = await self._reconcile_suspension(connection, suspension_id)
                await connection.execute(
                    "INSERT INTO inbox_events(event_id,event_type) VALUES($1,$2)", event_id, kind
                )
                return sequence
            if kind == "porfirium.message.started.v1":
                await connection.execute(
                    "INSERT INTO messages(message_id,conversation_id,run_id,role,status,content) VALUES($1,$2,$3,'assistant','streaming','') ON CONFLICT(message_id) DO NOTHING",
                    mid,
                    conversation_id,
                    run_id,
                )
            elif kind == "porfirium.message.delta.v1":
                await self._require_streaming(connection, mid, conversation_id)
                chunk = int(data.get("chunk_sequence", 0))
                content = str(data.get("content", ""))
                if chunk < 1 or not content or len(content.encode()) > 4096:
                    raise ConversationProblem(422, "delta_invalid", "Message delta is invalid")
                old = await connection.fetchval(
                    "SELECT content FROM message_chunks WHERE message_id=$1 AND chunk_sequence=$2",
                    mid,
                    chunk,
                )
                if old is not None and old != content:
                    raise ConversationProblem(409, "delta_conflict", "Chunk sequence conflicts")
                await connection.execute(
                    "INSERT INTO message_chunks(message_id,chunk_sequence,content) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
                    mid,
                    chunk,
                    content,
                )
            elif kind == "porfirium.message.completed.v1":
                await self._require_streaming(connection, mid, conversation_id)
                rows = await connection.fetch(
                    "SELECT chunk_sequence,content FROM message_chunks WHERE message_id=$1", mid
                )
                content = validate_completion(
                    data, {int(r["chunk_sequence"]): r["content"] for r in rows}
                )
                await connection.execute(
                    "UPDATE messages SET status='completed',content=$2,finish_reason=$3,usage=$4::jsonb,completed_at=now() WHERE message_id=$1",
                    mid,
                    content,
                    str(data.get("finish_reason", "stop")),
                    canonical_json(data.get("usage") or {}).decode(),
                )
                proposal = await connection.fetchrow(
                    "SELECT final_message_ids FROM result_proposals WHERE run_id=$1", run_id
                )
                if proposal:
                    completed = await connection.fetchval(
                        "SELECT count(*) FROM messages WHERE run_id=$1 AND "
                        "message_id=ANY($2::uuid[]) AND status='completed'",
                        run_id, proposal["final_message_ids"],
                    )
                    if completed == len(proposal["final_message_ids"]):
                        await self._confirm_messages(
                            connection, run_id, list(proposal["final_message_ids"])
                        )
            elif kind in {"porfirium.message.interrupted.v1", "porfirium.message.failed.v1"}:
                await self._require_streaming(connection, mid, conversation_id)
                rows = await connection.fetch(
                    "SELECT content FROM message_chunks WHERE message_id=$1 ORDER BY chunk_sequence",
                    mid,
                )
                content = "".join(r["content"] for r in rows)
                state = "interrupted" if "interrupted" in kind else "failed"
                await connection.execute(
                    "UPDATE messages SET status=$2,content=$3,completed_at=now() WHERE message_id=$1",
                    mid,
                    state,
                    content,
                )
            elif kind == "porfirium.input.request_proposed.v1":
                suspension_id = UUID(str(data["suspension_id"]))
                request_id = uuid5(NAMESPACE_URL, f"porfirium:suspension:{suspension_id}")
                await connection.execute(
                    "INSERT INTO input_requests(input_request_id,conversation_id,run_id,"
                    "suspension_id,checkpoint_id,prompt,schema,state,delegation_grant_id) "
                    "VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,'reserved',"
                    "(SELECT delegation_grant_id FROM conversations WHERE conversation_id=$2)) "
                    "ON CONFLICT(suspension_id) DO NOTHING",
                    request_id,
                    conversation_id,
                    run_id,
                    suspension_id,
                    UUID(str(data["checkpoint_id"])),
                    str(data["prompt"]),
                    canonical_json(data.get("response_schema") or data.get("schema") or {}).decode(),
                )
                committed_sequence = await self._reconcile_suspension(connection, suspension_id)
                await connection.execute(
                    "INSERT INTO inbox_events(event_id,event_type) VALUES($1,$2)", event_id, kind
                )
                return committed_sequence
            else:
                raise ConversationProblem(
                    422, "event_unsupported", "Runtime event type is unsupported"
                )
            sequence = await self._present(connection, conversation_id, kind, data)
            await connection.execute(
                "INSERT INTO inbox_events(event_id,event_type) VALUES($1,$2)", event_id, kind
            )
            return sequence

    async def _reconcile_suspension(
        self, connection: asyncpg.Connection, suspension_id: UUID
    ) -> int | None:
        row = await connection.fetchrow(
            "SELECT r.*,c.input_request_id committed_request_id,c.checkpoint_id committed_checkpoint,"
            "c.run_id committed_run_id "
            "FROM input_requests r JOIN suspension_commitments c USING(suspension_id) "
            "WHERE r.suspension_id=$1 FOR UPDATE OF r", suspension_id
        )
        if row is None:
            return None
        if (
            row["input_request_id"] != row["committed_request_id"]
            or row["checkpoint_id"] != row["committed_checkpoint"]
            or row["run_id"] != row["committed_run_id"]
        ):
            raise ConversationProblem(409, "suspension_conflict", "Suspension identity conflicts")
        if row["state"] != "reserved":
            return None
        await connection.execute(
            "UPDATE input_requests SET state='pending' WHERE suspension_id=$1", suspension_id
        )
        data = {
            "input_request_id": str(row["input_request_id"]),
            "suspension_id": str(suspension_id), "checkpoint_id": str(row["checkpoint_id"]),
            "prompt": row["prompt"], "response_schema": row["schema"], "expires_at": None,
        }
        return await self._present(connection, row["conversation_id"], "input.request_created", data)

    async def _confirm_messages(
        self, connection: asyncpg.Connection, run_id: UUID, message_ids: list[UUID]
    ) -> None:
        existing = await connection.fetchval(
            "SELECT confirmation_event_id FROM result_proposals WHERE run_id=$1", run_id
        )
        if existing:
            return
        event_id = uuid4()
        sequence = await connection.fetchval(
            "SELECT max(sequence) FROM presentation_events p JOIN result_proposals r "
            "USING(conversation_id) WHERE r.run_id=$1", run_id
        )
        payload = {
            "specversion": "1.0", "type": "porfirium.run.messages_committed.v1",
            "id": str(event_id), "source": "conversation-service", "run_id": str(run_id),
            "schema_version": 1,
            "data": {"run_id": str(run_id), "message_ids": [str(value) for value in message_ids],
                     "conversation_sequence": max(1, int(sequence or 1))},
        }
        await connection.execute(
            "INSERT INTO outbox_events(event_id,subject,payload) "
            "VALUES($1,'porfirium.run.event.messages_committed',$2::jsonb)",
            event_id, canonical_json(payload).decode(),
        )
        await connection.execute(
            "UPDATE result_proposals SET confirmation_event_id=$2 WHERE run_id=$1", run_id, event_id
        )

    async def _require_streaming(
        self, connection: asyncpg.Connection, message_id: UUID | None, conversation_id: UUID
    ) -> None:
        state = await connection.fetchval(
            "SELECT status FROM messages WHERE message_id=$1 AND conversation_id=$2 FOR UPDATE",
            message_id,
            conversation_id,
        )
        if state is None:
            raise ConversationProblem(409, "message_not_started", "Message has not started")
        if state != "streaming":
            raise ConversationProblem(409, "message_terminal", "Message is already terminal")

    async def answer_input(
        self, owner_id: UUID, request_id: UUID, idempotency_key: str, run_id: UUID, response: Any
    ) -> tuple[UUID, int]:
        digest = hashlib.sha256(
            canonical_json({"run_id": run_id, "response": response})
        ).hexdigest()
        operation = f"input:{request_id}"
        async with self.pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                "SELECT r.*,c.owner_id,c.thread_id,c.release_id,c.configuration_revision_id "
                "FROM input_requests r JOIN conversations c USING(conversation_id) "
                "WHERE input_request_id=$1 AND c.owner_id=$2 FOR UPDATE",
                request_id,
                owner_id,
            )
            if not row:
                raise ConversationProblem(
                    404, "input_request_not_found", "Input request was not found"
                )
            old = await connection.fetchrow(
                "SELECT * FROM request_idempotency WHERE owner_id=$1 AND operation=$2 AND idempotency_key=$3 FOR UPDATE",
                owner_id,
                operation,
                idempotency_key,
            )
            if old:
                if old["request_sha256"] != digest:
                    raise ConversationProblem(
                        409, "idempotency_conflict", "Idempotency key was reused"
                    )
                return request_id, int(old["conversation_sequence"])
            if row["state"] != "pending":
                raise ConversationProblem(
                    409, "input_already_answered", "Input request was already answered"
                )
            await connection.execute(
                "UPDATE input_requests SET state='answered',response=$2::jsonb,response_run_id=$3,answered_at=now() WHERE input_request_id=$1",
                request_id,
                canonical_json(response).decode(),
                run_id,
            )
            sequence = await self._present(
                connection,
                row["conversation_id"],
                "input.response.accepted",
                {"input_request_id": str(request_id)},
            )
            event_id = uuid4()
            event = {
                "type": "porfirium.run.requested.v1",
                "id": str(event_id),
                "user_id": str(owner_id),
                "conversation_id": str(row["conversation_id"]),
                "thread_id": str(row["thread_id"]),
                "release_id": str(row["release_id"]),
                "run_id": str(run_id),
                "delegation_grant_id": str(row["delegation_grant_id"]),
                "configuration_revision_id": (
                    str(row["configuration_revision_id"])
                    if row["configuration_revision_id"] else None
                ),
                "starting_checkpoint_id": str(row["checkpoint_id"]),
                "trigger": {"type": "user_response", "id": str(request_id)},
                "trace_id": event_id.hex,
                "schema_version": 1,
            }
            await connection.execute(
                "INSERT INTO outbox_events(event_id,subject,payload) VALUES($1,'porfirium.run.command.requested',$2::jsonb)",
                event_id,
                canonical_json(event).decode(),
            )
            await connection.execute(
                "INSERT INTO request_idempotency VALUES($1,$2,$3,$4,$5,$6)",
                owner_id,
                operation,
                idempotency_key,
                digest,
                request_id,
                sequence,
            )
            return request_id, sequence
