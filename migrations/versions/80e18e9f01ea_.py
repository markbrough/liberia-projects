"""empty message

Revision ID: 80e18e9f01ea
Revises: f5799f295477
Create Date: 2019-08-02 18:55:46.776184

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '80e18e9f01ea'
down_revision = 'f5799f295477'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('maediuser', sa.Column('reset_password_expiry', sa.DateTime(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('maediuser', 'reset_password_expiry')
    # ### end Alembic commands ###
