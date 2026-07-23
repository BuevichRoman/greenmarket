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
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_endpoint_url: str = ""
    s3_public_base_url: str = ""
    test_db_name: str = ""


settings = Settings()
