"""Fix relationship definition conflict

Revision ID: 00b41dc9af1e
Revises: cc01e67a4637
Create Date: 2025-04-09 15:29:08.993883

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '00b41dc9af1e'
down_revision = 'cc01e67a4637'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('reconciliation_type', schema=None) as batch_op:
        batch_op.add_column(sa.Column('name', sa.String(length=100), nullable=False))
        batch_op.add_column(sa.Column('description', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('knowledge_base_content', sa.Text(), nullable=False))
        batch_op.add_column(sa.Column('ai_prompt_template', sa.Text(), nullable=False))
        batch_op.add_column(sa.Column('candidate_selection_strategy', sa.String(length=50), nullable=True))
        batch_op.create_unique_constraint(None, ['name'])

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('reconciliation_type', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='unique')
        batch_op.drop_column('candidate_selection_strategy')
        batch_op.drop_column('ai_prompt_template')
        batch_op.drop_column('knowledge_base_content')
        batch_op.drop_column('description')
        batch_op.drop_column('name')

    # ### end Alembic commands ###
