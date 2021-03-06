"""empty message

Revision ID: 2910cdc38aaf
Revises: 186fbfd0d196
Create Date: 2019-04-18 23:07:17.361697

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2910cdc38aaf'
down_revision = '186fbfd0d196'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('activitydocumentlink',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('activity_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.UnicodeText(), nullable=True),
    sa.Column('url', sa.UnicodeText(), nullable=True),
    sa.Column('document_date', sa.Date(), nullable=True),
    sa.ForeignKeyConstraint(['activity_id'], ['activity.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_activitydocumentlink_activity_id'), 'activitydocumentlink', ['activity_id'], unique=False)
    op.create_table('activitydocumentlinkcategory',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('activitydocumentlink_id', sa.Integer(), nullable=False),
    sa.Column('code', sa.UnicodeText(), nullable=True),
    sa.ForeignKeyConstraint(['activitydocumentlink_id'], ['activitydocumentlink.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_activitydocumentlinkcategory_activitydocumentlink_id'), 'activitydocumentlinkcategory', ['activitydocumentlink_id'], unique=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_activitydocumentlinkcategory_activitydocumentlink_id'), table_name='activitydocumentlinkcategory')
    op.drop_table('activitydocumentlinkcategory')
    op.drop_index(op.f('ix_activitydocumentlink_activity_id'), table_name='activitydocumentlink')
    op.drop_table('activitydocumentlink')
    # ### end Alembic commands ###
