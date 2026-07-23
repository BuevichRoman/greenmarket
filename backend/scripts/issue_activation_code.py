"""Admin CLI: выдать/перевыпустить activation_code для существующего продавца.

Использование (из backend/):
    uv run python scripts/issue_activation_code.py <seller_id>

Печатает код в stdout — админ передаёт его продавцу вручную (WhatsApp/
телефон, оба поля обязательны в Seller_Profile.md). См.
docs/superpowers/specs/2026-07-23-seller-activation-auth-design.md.
"""

import argparse
import sys

from app.infrastructure.database import SessionLocal
from app.publication.seller_activation import issue_activation_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Выдать activation_code продавцу")
    parser.add_argument("seller_id", type=int)
    args = parser.parse_args()

    session = SessionLocal()
    try:
        code = issue_activation_code(args.seller_id, session=session)
        if code is None:
            print(f"Seller {args.seller_id} не найден", file=sys.stderr)
            raise SystemExit(1)
        session.commit()
    finally:
        session.close()

    print(f"activation_code: {code}")


if __name__ == "__main__":
    main()
