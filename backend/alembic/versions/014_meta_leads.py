"""Meta Lead Ads webhook: meta_leads log and the form → store mapping

meta_leads keeps every Facebook/Instagram lead-form submission received by
the webhook (ad, ad set, campaign, answers) and links it to the CRM lead it
created or was merged into. meta_form_stores maps each lead form to a store
so the lead is routed to that store's team leader. Additive only.

Revision ID: 014
Revises: 013
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meta_leads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("leadgen_id", sa.String(40), nullable=False),
        sa.Column("page_id", sa.String(40), nullable=True),
        sa.Column("form_id", sa.String(40), nullable=True),
        sa.Column("form_name", sa.String(200), nullable=True),
        sa.Column("ad_id", sa.String(40), nullable=True),
        sa.Column("ad_name", sa.String(200), nullable=True),
        sa.Column("adset_id", sa.String(40), nullable=True),
        sa.Column("adset_name", sa.String(200), nullable=True),
        sa.Column("campaign_id", sa.String(40), nullable=True),
        sa.Column("campaign_name", sa.String(200), nullable=True),
        sa.Column("platform", sa.String(20), nullable=True),
        sa.Column("is_organic", sa.Boolean(), nullable=True),
        sa.Column("full_name", sa.String(200), nullable=True),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("phone_brand", sa.String(60), nullable=True),
        sa.Column("prebook_answer", sa.String(20), nullable=True),
        sa.Column("phone_verified", sa.Boolean(), nullable=True),
        sa.Column("is_hot", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("field_data", sa.JSON(), nullable=True),
        sa.Column("meta_created_at", sa.DateTime(), nullable=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", name="fk_meta_leads_store"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="created"),
        sa.Column("error", sa.String(300), nullable=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("tele_call_leads.id", ondelete="SET NULL",
                                                          name="fk_meta_leads_lead"), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("leadgen_id", name="uq_meta_leads_leadgen_id"),
    )
    op.create_index("ix_meta_leads_form_id", "meta_leads", ["form_id"])
    op.create_index("ix_meta_leads_lead_id", "meta_leads", ["lead_id"])

    op.create_table(
        "meta_form_stores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("form_id", sa.String(40), nullable=False),
        sa.Column("form_name", sa.String(200), nullable=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", name="fk_meta_form_stores_store"), nullable=True),
        sa.Column("match_source", sa.String(20), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id", name="fk_meta_form_stores_user"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("form_id", name="uq_meta_form_stores_form_id"),
    )


def downgrade() -> None:
    op.drop_table("meta_form_stores")
    op.drop_index("ix_meta_leads_lead_id", table_name="meta_leads")
    op.drop_index("ix_meta_leads_form_id", table_name="meta_leads")
    op.drop_table("meta_leads")
