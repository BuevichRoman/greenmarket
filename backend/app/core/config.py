from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    google_service_account_file: str = ""
    google_sheets_timeout_seconds: float = 10.0


settings = Settings()
