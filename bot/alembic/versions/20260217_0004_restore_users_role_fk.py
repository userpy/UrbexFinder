"""restore users.role_id foreign key

Revision ID: 20260217_0004
Revises: 20260217_0003
Create Date: 2026-02-17 23:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260217_0004"
down_revision: Union[str, Sequence[str], None] = "20260217_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROLE_FK_NAME = "users_role_id_fkey"


def upgrade() -> None:
    # Гарантируем наличие базовой роли user с id=1 для фикса «осиротевших» role_id.
    op.execute(
        sa.text(
            """
            INSERT INTO roles (id, name)
            SELECT 1, 'user'
            WHERE NOT EXISTS (SELECT 1 FROM roles WHERE id = 1)
            """
        )
    )

    # Если в users есть role_id без соответствующей роли, переводим их на user (id=1).
    op.execute(
        sa.text(
            """
            UPDATE users
            SET role_id = 1
            WHERE role_id IS NULL
               OR role_id NOT IN (SELECT id FROM roles)
            """
        )
    )

    op.create_foreign_key(
        ROLE_FK_NAME,
        source_table="users",
        referent_table="roles",
        local_cols=["role_id"],
        remote_cols=["id"],
    )


def downgrade() -> None:
    op.drop_constraint(ROLE_FK_NAME, "users", type_="foreignkey")
