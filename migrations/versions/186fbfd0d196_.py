"""empty message

Revision ID: 186fbfd0d196
Revises: 460a1cf214a7
Create Date: 2019-04-11 20:27:42.865487

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '186fbfd0d196'
down_revision = '460a1cf214a7'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('activityfinances', sa.Column('currency_automatic', sa.Boolean(), server_default="1", nullable=False))
    op.add_column('activityfinances', sa.Column('currency_rate', sa.Float(), server_default="1", nullable=False))
    op.add_column('activityfinances', sa.Column('currency_source', sa.UnicodeText(), server_default=u"USD", nullable=False))
    op.add_column('activityfinances', sa.Column('currency_value_date', sa.Date(), nullable=True))
    op.add_column('activityfinances', sa.Column('transaction_value_original', sa.Float(precision=2), server_default="0", nullable=False))
    # ### end Alembic commands ###
    op.execute("UPDATE activityfinances SET transaction_value_original = transaction_value;")
    op.execute("UPDATE activityfinances SET currency_value_date = transaction_date;")

    # We need default values above for the migration, but we drop them
    # again now because we want the database to enforce these constraints.
    with op.batch_alter_table("activityfinances") as batch_op:
        batch_op.alter_column("currency_automatic", server_default=None)
        batch_op.alter_column("currency_rate", server_default=None)
        batch_op.alter_column("currency_source", server_default=None)
        batch_op.alter_column("currency_value_date", server_default=None)
        batch_op.alter_column("transaction_value_original", server_default=None)

    # Create exchange rate columns
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('currency',
    sa.Column('code', sa.UnicodeText(), nullable=False),
    sa.Column('name', sa.UnicodeText(), nullable=False),
    sa.PrimaryKeyConstraint('code')
    )
    op.create_table('exchangeratesource',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.UnicodeText(), nullable=False),
    sa.Column('weight', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('exchangerate',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('exchangeratesource_id', sa.Integer(), nullable=False),
    sa.Column('currency_code', sa.UnicodeText(), nullable=False),
    sa.Column('rate_date', sa.Date(), nullable=False),
    sa.Column('rate', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['currency_code'], ['currency.code'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['exchangeratesource_id'], ['exchangeratesource.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_exchangerate_currency_code'), 'exchangerate', ['currency_code'], unique=False)
    op.create_index(op.f('ix_exchangerate_exchangeratesource_id'), 'exchangerate', ['exchangeratesource_id'], unique=False)
    op.create_index(op.f('ix_exchangerate_rate_date'), 'exchangerate', ['rate_date'], unique=False)
    # ### end Alembic commands ###

def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('activityfinances', 'transaction_value_original')
    op.drop_column('activityfinances', 'currency_value_date')
    op.drop_column('activityfinances', 'currency_source')
    op.drop_column('activityfinances', 'currency_rate')
    op.drop_column('activityfinances', 'currency_automatic')
    # ### end Alembic commands ###
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_exchangerate_rate_date'), table_name='exchangerate')
    op.drop_index(op.f('ix_exchangerate_exchangeratesource_id'), table_name='exchangerate')
    op.drop_index(op.f('ix_exchangerate_currency_code'), table_name='exchangerate')
    op.drop_table('exchangerate')
    op.drop_table('exchangeratesource')
    op.drop_table('currency')
    # ### end Alembic commands ###
