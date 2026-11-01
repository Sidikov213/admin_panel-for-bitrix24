"""Allow a payload to recur in deal history (A -> B -> A)."""
from alembic import op

revision = "20261028_0008"
down_revision = "20261013_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("uq_deal_snapshots_deal_hash", "deal_snapshots", type_="unique")


def downgrade():
    # Deliberately fail if recurring payloads exist; never delete audit history.
    op.create_unique_constraint("uq_deal_snapshots_deal_hash", "deal_snapshots", ["deal_id", "content_hash"])
