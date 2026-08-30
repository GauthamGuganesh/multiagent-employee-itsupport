"""Persist the opaque key that groups utterances in one voice session."""

from alembic import op
import sqlalchemy as sa


revision = "5a2c42fbd101"
down_revision = "044385a0396d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("support_sessions", sa.Column("voice_bridge_key", sa.String(length=64), nullable=True))
    op.create_index("ix_support_sessions_voice_bridge_key", "support_sessions", ["voice_bridge_key"])


def downgrade() -> None:
    op.drop_index("ix_support_sessions_voice_bridge_key", table_name="support_sessions")
    op.drop_column("support_sessions", "voice_bridge_key")
