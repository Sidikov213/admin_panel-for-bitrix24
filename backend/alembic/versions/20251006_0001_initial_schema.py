"""initial schema

Revision ID: 20251006_0001
Revises:
Create Date: 2025-10-06

"""

from typing import Sequence, Union

from alembic import op

revision: str = "20251006_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    import app.models  # noqa: F401
    from app.db.base import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    import app.models  # noqa: F401
    from app.db.base import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
