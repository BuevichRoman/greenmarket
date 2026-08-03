"""Admin CLI: завести администратора GreenMarket и выдать ему код активации.

Использование (из backend/):
    uv run python scripts/issue_admin_activation_code.py <user_id>

`user_id` — идентификатор пользователя платформы (`aristotel_taxi.users.id_user`).
Учётная запись администратора создаётся при первом вызове, повторный вызов
просто перевыпускает код (предыдущий перестаёт действовать).

Печатает код в stdout — админ обменивает его на постоянный токен через
POST /api/v1/admin/activate. Роль пользователя на платформе (`users.id_role`)
намеренно не проверяется, см. database/migrations/013_create_administrator.sql.
"""

import argparse
import sys

from app.admin.admin_activation import issue_admin_activation_code
from app.infrastructure.database import SessionLocal
from app.infrastructure.repositories.administrator_repository import AdministratorRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Выдать activation_code администратору")
    parser.add_argument("user_id", type=int, help="users.id_user платформы")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        repository = AdministratorRepository(session)
        administrator = repository.find_by_user_id(args.user_id)
        created = administrator is None
        if administrator is None:
            administrator = repository.create(user_id=args.user_id)

        code = issue_admin_activation_code(administrator.id, session=session)
        if code is None:
            print(f"Не удалось выдать код администратору {administrator.id}", file=sys.stderr)
            raise SystemExit(1)
        admin_id = administrator.id
        session.commit()
    finally:
        session.close()

    print(f"admin_id: {admin_id}{' (создан)' if created else ''}")
    print(f"activation_code: {code}")


if __name__ == "__main__":
    main()
