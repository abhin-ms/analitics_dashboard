"""telecalling CRM layer on top of the sheet-synced tele_call_leads

Adds app-owned CRM fields to tele_call_leads (owner, stage, priority,
follow-up timing, device/value) plus the tables for the lead timeline,
follow-ups, appointments, alerts, price book and saved views.

Purely additive: every new column is nullable, nothing existing is
altered or dropped, and downgrade removes only what this adds. The
Google Sheet stays the intake source and is never written to.

Existing rows are back-filled (owner from "Person Calling", stage and
priority from status, submitted_at from "Created Time") by the first
tele-call sync after this migration, via app.services.crm.sync_hooks —
not here — so the same parsing code runs in both places.

Revision ID: 011
Revises: 010
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def _lead_columns():
    return [
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", name="fk_tele_leads_owner"), nullable=True),
        sa.Column("assigned_at", sa.DateTime(), nullable=True),
        sa.Column("assignment_source", sa.String(20), nullable=True),
        sa.Column("reassign_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("first_contact_at", sa.DateTime(), nullable=True),
        sa.Column("last_contact_at", sa.DateTime(), nullable=True),
        sa.Column("next_follow_up_at", sa.DateTime(), nullable=True),
        sa.Column("is_urgent", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("escalated_at", sa.DateTime(), nullable=True),
        sa.Column("stage", sa.String(30), nullable=True),
        sa.Column("stage_manual", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("priority", sa.String(10), nullable=True),
        sa.Column("priority_manual", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("phone_model", sa.String(100), nullable=True),
        sa.Column("service_type", sa.String(100), nullable=True),
        sa.Column("coverage", sa.String(50), nullable=True),
        sa.Column("potential_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("sheet_status_raw", sa.String(100), nullable=True),
        sa.Column("edited_fields", sa.JSON(), nullable=True),
    ]


def upgrade() -> None:
    for col in _lead_columns():
        op.add_column("tele_call_leads", col)
    op.create_index("ix_tele_call_leads_owner_user_id", "tele_call_leads", ["owner_user_id"])
    op.create_index("ix_tele_call_leads_next_follow_up_at", "tele_call_leads", ["next_follow_up_at"])
    op.create_index("ix_tele_leads_tl_stage", "tele_call_leads", ["sheet_tl_name", "stage"])

    op.add_column(
        "users",
        sa.Column("available_for_leads", sa.Boolean(), nullable=True, server_default=sa.true()),
    )

    op.create_table(
        "tele_lead_activities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("tele_call_leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("outcome", sa.String(40), nullable=True),
        sa.Column("old_value", sa.String(200), nullable=True),
        sa.Column("new_value", sa.String(200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_tele_act_lead_time", "tele_lead_activities", ["lead_id", "created_at"])
    op.create_index("ix_tele_act_user_time", "tele_lead_activities", ["user_id", "created_at"])

    op.create_table(
        "tele_lead_followups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("tele_call_leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("outcome", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("attempt_no", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_tele_fu_owner_status_due", "tele_lead_followups", ["owner_user_id", "status", "due_at"])
    op.create_index("ix_tele_fu_lead_status", "tele_lead_followups", ["lead_id", "status"])

    op.create_table(
        "tele_appointments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("tele_call_leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("purpose", sa.String(200), nullable=True),
        sa.Column("attendance", sa.String(20), nullable=False, server_default="scheduled"),
        sa.Column("source", sa.String(10), nullable=False, server_default="app"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_tele_appt_time", "tele_appointments", ["scheduled_at"])

    op.create_table(
        "crm_alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("tele_call_leads.id", ondelete="CASCADE"), nullable=True),
        sa.Column("followup_id", sa.Integer(), sa.ForeignKey("tele_lead_followups.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recipient_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("level", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledged_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("dedupe_key", sa.String(150), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("dedupe_key", name="uq_crm_alerts_dedupe_key"),
    )
    op.create_index("ix_crm_alert_recipient", "crm_alerts", ["recipient_user_id", "resolved_at"])

    op.create_table(
        "price_book_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("phone_model", sa.String(100), nullable=False),
        sa.Column("service_type", sa.String(100), nullable=False),
        sa.Column("coverage", sa.String(50), nullable=False, server_default="Standard"),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("phone_model", "service_type", "coverage", name="uq_price_book_entry"),
    )

    op.create_table(
        "crm_saved_views",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page", sa.String(50), nullable=False, server_default="leads"),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=True),
        sa.Column("columns", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("crm_saved_views")
    op.drop_table("price_book_entries")
    op.drop_index("ix_crm_alert_recipient", table_name="crm_alerts")
    op.drop_table("crm_alerts")
    op.drop_index("ix_tele_appt_time", table_name="tele_appointments")
    op.drop_table("tele_appointments")
    op.drop_index("ix_tele_fu_lead_status", table_name="tele_lead_followups")
    op.drop_index("ix_tele_fu_owner_status_due", table_name="tele_lead_followups")
    op.drop_table("tele_lead_followups")
    op.drop_index("ix_tele_act_user_time", table_name="tele_lead_activities")
    op.drop_index("ix_tele_act_lead_time", table_name="tele_lead_activities")
    op.drop_table("tele_lead_activities")

    op.drop_column("users", "available_for_leads")

    # MySQL: drop the foreign key before the index it relies on.
    op.drop_constraint("fk_tele_leads_owner", "tele_call_leads", type_="foreignkey")
    op.drop_index("ix_tele_leads_tl_stage", table_name="tele_call_leads")
    op.drop_index("ix_tele_call_leads_next_follow_up_at", table_name="tele_call_leads")
    op.drop_index("ix_tele_call_leads_owner_user_id", table_name="tele_call_leads")
    for col in reversed(_lead_columns()):
        op.drop_column("tele_call_leads", col.name)
