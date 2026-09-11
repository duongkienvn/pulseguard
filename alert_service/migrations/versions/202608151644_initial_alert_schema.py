"""initial alert schema

Revision ID: 202608151644
Revises:
Create Date: 2026-08-15 16:44:00
"""
from alembic import op
import sqlalchemy as sa

revision = "202608151644"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("metric_type", sa.String(), nullable=True),
        sa.Column("condition", sa.String(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_rules_agent_id", "alert_rules", ["agent_id"], unique=False)
    op.create_index("ix_alert_rules_id", "alert_rules", ["id"], unique=False)
    op.create_index("ix_alert_rules_user_id", "alert_rules", ["user_id"], unique=False)

    op.create_table(
        "alert_recipients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("telegram_chat_id", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_recipients_id", "alert_recipients", ["id"], unique=False)
    op.create_index("ix_alert_recipients_user_id", "alert_recipients", ["user_id"], unique=True)

    op.create_table(
        "alert_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column("agent_name", sa.String(), nullable=True),
        sa.Column("metric_type", sa.String(), nullable=True),
        sa.Column("condition", sa.String(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("message", sa.String(), nullable=True),
        sa.Column("triggered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_history_agent_id", "alert_history", ["agent_id"], unique=False)
    op.create_index("ix_alert_history_id", "alert_history", ["id"], unique=False)
    op.create_index("ix_alert_history_triggered_at", "alert_history", ["triggered_at"], unique=False)
    op.create_index("ix_alert_history_user_id", "alert_history", ["user_id"], unique=False)


def downgrade():
    op.drop_index("ix_alert_history_user_id", table_name="alert_history")
    op.drop_index("ix_alert_history_triggered_at", table_name="alert_history")
    op.drop_index("ix_alert_history_id", table_name="alert_history")
    op.drop_index("ix_alert_history_agent_id", table_name="alert_history")
    op.drop_table("alert_history")
    op.drop_index("ix_alert_recipients_user_id", table_name="alert_recipients")
    op.drop_index("ix_alert_recipients_id", table_name="alert_recipients")
    op.drop_table("alert_recipients")
    op.drop_index("ix_alert_rules_user_id", table_name="alert_rules")
    op.drop_index("ix_alert_rules_id", table_name="alert_rules")
    op.drop_index("ix_alert_rules_agent_id", table_name="alert_rules")
    op.drop_table("alert_rules")
