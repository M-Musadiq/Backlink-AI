"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-07-15
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tracked_urls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("title", sa.String(500), server_default=""),
        sa.Column("source", sa.String(50), server_default=""),
        sa.Column("status", sa.String(50), server_default="discovered"),
        sa.Column("discovered_at", sa.DateTime(), nullable=True),
        sa.Column("last_checked", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url"),
    )
    op.create_index("ix_tracked_urls_url", "tracked_urls", ["url"])
    op.create_index("ix_tracked_urls_domain", "tracked_urls", ["domain"])
    op.create_index("ix_tracked_urls_status", "tracked_urls", ["status"])

    op.create_table(
        "platform_config",
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("scraper_type", sa.String(50), server_default="static"),
        sa.Column("post_method", sa.String(50), server_default="not_supported"),
        sa.Column("requires_auth", sa.Boolean(), server_default="false"),
        sa.Column("rate_limit_seconds", sa.Integer(), server_default="5"),
        sa.Column("guidelines_url", sa.String(2048), server_default=""),
        sa.Column("last_updated", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("domain"),
    )

    op.create_table(
        "guidelines_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("scraped_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("scraper_type_used", sa.String(50), server_default=""),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_guidelines_cache_domain", "guidelines_cache", ["domain"])

    op.create_table(
        "prospects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tracked_url_id", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("title", sa.String(500), server_default=""),
        sa.Column("body_preview", sa.Text(), server_default=""),
        sa.Column("relevance_score", sa.Float(), server_default="0.0"),
        sa.Column("status", sa.String(50), server_default="discovered"),
        sa.Column("draft_content", sa.Text(), server_default=""),
        sa.Column("posted_url", sa.String(2048), server_default=""),
        sa.Column("feedback_notes", sa.Text(), server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tracked_url_id"], ["tracked_urls.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prospects_domain", "prospects", ["domain"])
    op.create_index("ix_prospects_status", "prospects", ["status"])

    op.create_table(
        "platform_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("session_data_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain"),
    )
    op.create_index("ix_platform_sessions_domain", "platform_sessions", ["domain"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prospect_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("details", sa.Text(), server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["prospect_id"], ["prospects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("platform_sessions")
    op.drop_table("prospects")
    op.drop_table("guidelines_cache")
    op.drop_table("platform_config")
    op.drop_table("tracked_urls")
