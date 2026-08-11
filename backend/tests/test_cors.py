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


def test_preflight_allows_second_frontend_origin():
    """Сборка заместителя фронтендера (11.08.2026) — второй домен, не замена
    первому: обе сборки живут одновременно."""
    response = client.options(
        "/api/v1/catalog/groups",
        headers={
            "Origin": "https://basket-ef9u.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://basket-ef9u.vercel.app"


def test_preflight_allows_vercel_preview_subdomain():
    response = client.options(
        "/api/v1/catalog/groups",
        headers={
            "Origin": "https://basket-ef9u-git-main-user.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers["access-control-allow-origin"] == "https://basket-ef9u-git-main-user.vercel.app"


def test_preflight_rejects_unknown_origin():
    """Регулярное выражение не должно превратиться в «любой vercel.app»."""
    response = client.options(
        "/api/v1/catalog/groups",
        headers={
            "Origin": "https://someone-else.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers
