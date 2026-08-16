"""Phase 3 durable agent workflow identity."""

import sqlalchemy as sa
from alembic import op

revision = "0003_phase3"
down_revision = "0002_phase2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("turns", sa.Column("workflow_id", sa.String(255)))
    op.create_unique_constraint("uq_turns_workflow_id", "turns", ["workflow_id"])


def downgrade() -> None:
    op.drop_constraint("uq_turns_workflow_id", "turns", type_="unique")
    op.drop_column("turns", "workflow_id")
