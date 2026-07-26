from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_preflight_allows_customer_ui_origin():
    response = client.options(
        "/api/v1/catalog/groups",
        headers={
            "Origin": "https://green-market-nine.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://green-market-nine.vercel.app"
