from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapacityLimits:
    global_runs: int = 32
    per_user_runs: int = 4

    def __post_init__(self) -> None:
        if self.global_runs < 1 or self.per_user_runs < 1:
            raise ValueError("capacity limits must be positive")
        if self.per_user_runs > self.global_runs:
            raise ValueError("per-user capacity cannot exceed global capacity")


async def has_capacity(connection: object, user_id: object, limits: CapacityLimits) -> bool:
    # Serialize capacity decisions across Runner replicas inside the caller's transaction.
    await connection.execute("SELECT pg_advisory_xact_lock(742731912)")
    counts = await connection.fetchrow(
        """SELECT
             count(*) FILTER (WHERE state IN ('starting','running','suspending','cancelling'))
                 AS global_active,
             count(*) FILTER (WHERE user_id=$1 AND state IN
                 ('starting','running','suspending','cancelling')) AS user_active
           FROM runs""",
        user_id,
    )
    return (
        int(counts["global_active"]) < limits.global_runs
        and int(counts["user_active"]) < limits.per_user_runs
    )
