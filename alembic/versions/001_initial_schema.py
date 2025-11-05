"""Initial database schema with jobs and quality scores

Revision ID: 001
Revises: 
Create Date: 2024-01-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create documentation_jobs table
    op.create_table('documentation_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('team_id', sa.String(length=100), nullable=False),
        sa.Column('service_name', sa.String(length=200), nullable=False),
        sa.Column('spec_format', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('specification_hash', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_documentation_jobs_team_id', 'documentation_jobs', ['team_id'], unique=False)
    op.create_index('ix_documentation_jobs_service_name', 'documentation_jobs', ['service_name'], unique=False)
    op.create_index('ix_documentation_jobs_status', 'documentation_jobs', ['status'], unique=False)
    op.create_index('ix_documentation_jobs_created_at', 'documentation_jobs', ['created_at'], unique=False)

    # Create quality_scores table
    op.create_table('quality_scores',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('overall_score', sa.Integer(), nullable=False),
        sa.Column('completeness_score', sa.Integer(), nullable=False),
        sa.Column('clarity_score', sa.Integer(), nullable=False),
        sa.Column('accuracy_score', sa.Integer(), nullable=False),
        sa.Column('feedback_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['documentation_jobs.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_quality_scores_job_id', 'quality_scores', ['job_id'], unique=False)
    op.create_index('ix_quality_scores_overall_score', 'quality_scores', ['overall_score'], unique=False)
    op.create_index('ix_quality_scores_created_at', 'quality_scores', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_quality_scores_created_at', table_name='quality_scores')
    op.drop_index('ix_quality_scores_overall_score', table_name='quality_scores')
    op.drop_index('ix_quality_scores_job_id', table_name='quality_scores')
    op.drop_table('quality_scores')
    
    op.drop_index('ix_documentation_jobs_created_at', table_name='documentation_jobs')
    op.drop_index('ix_documentation_jobs_status', table_name='documentation_jobs')
    op.drop_index('ix_documentation_jobs_service_name', table_name='documentation_jobs')
    op.drop_index('ix_documentation_jobs_team_id', table_name='documentation_jobs')
    op.drop_table('documentation_jobs')