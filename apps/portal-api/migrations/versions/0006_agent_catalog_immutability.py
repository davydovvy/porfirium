"""Enforce immutable published agent release content and grants."""

from alembic import op

revision = "0006_agent_immutable"
down_revision = "0005_agent_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_published_agent_version_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.status IN ('published', 'deprecated') THEN
            IF TG_OP = 'DELETE' THEN
              RAISE EXCEPTION 'published agent versions are immutable';
            END IF;
            IF NEW.agent_id IS DISTINCT FROM OLD.agent_id
               OR NEW.version IS DISTINCT FROM OLD.version
               OR NEW.digest IS DISTINCT FROM OLD.digest
               OR NEW.manifest IS DISTINCT FROM OLD.manifest
               OR NEW.model_alias_id IS DISTINCT FROM OLD.model_alias_id
               OR NEW.published_at IS DISTINCT FROM OLD.published_at THEN
              RAISE EXCEPTION 'published agent version content is immutable';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER agent_versions_immutable
        BEFORE UPDATE OR DELETE ON agent_versions
        FOR EACH ROW EXECUTE FUNCTION reject_published_agent_version_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_published_agent_grant_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE release_status text;
        BEGIN
          SELECT status INTO release_status
          FROM agent_versions
          WHERE id = COALESCE(OLD.agent_version_id, NEW.agent_version_id);
          IF release_status IN ('published', 'deprecated') THEN
            RAISE EXCEPTION 'published agent tool grants are immutable';
          END IF;
          RETURN COALESCE(NEW, OLD);
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER agent_tool_grants_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON agent_tool_grants
        FOR EACH ROW EXECUTE FUNCTION reject_published_agent_grant_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER agent_tool_grants_immutable ON agent_tool_grants")
    op.execute("DROP FUNCTION reject_published_agent_grant_mutation()")
    op.execute("DROP TRIGGER agent_versions_immutable ON agent_versions")
    op.execute("DROP FUNCTION reject_published_agent_version_mutation()")
