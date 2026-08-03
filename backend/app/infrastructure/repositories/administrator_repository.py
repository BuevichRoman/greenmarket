from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.infrastructure.models import Administrator


class AdministratorRepository:
    def __init__(self, session: Session):
        self.session = session

    def find_by_id(self, admin_id: int) -> Administrator | None:
        return self.session.get(Administrator, admin_id)

    def find_by_user_id(self, user_id: int) -> Administrator | None:
        return self.session.query(Administrator).filter(Administrator.user_id == user_id).first()

    def find_by_access_token(self, access_token: str) -> Administrator | None:
        if not access_token:
            return None
        return self.session.query(Administrator).filter(Administrator.access_token == access_token).first()

    def find_by_activation_code(self, activation_code: str) -> Administrator | None:
        if not activation_code:
            return None
        return self.session.query(Administrator).filter(Administrator.activation_code == activation_code).first()

    def create(self, *, user_id: int) -> Administrator:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        administrator = Administrator(
            user_id=user_id,
            is_active=True,
            access_token=None,
            activation_code=None,
            activation_code_expires_at=None,
            activated_at=None,
            created_at=now,
            updated_at=now,
        )
        self.session.add(administrator)
        self.session.flush()
        return administrator
