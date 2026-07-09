from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_app_and_database_up():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "UP", "database": "UP"}
