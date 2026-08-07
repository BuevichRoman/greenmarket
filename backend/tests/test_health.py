from pathlib import Path

from fastapi.testclient import TestClient

from app.core.deployed_commit import DEPLOYED_SHA_FILE, read_deployed_commit
from app.main import app

client = TestClient(app)


def test_health_reports_app_and_database_up():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "UP"
    assert body["database"] == "UP"


def test_health_reports_deployed_commit_key_even_without_the_file():
    """Ключ `commit` есть всегда, в том числе локально, где файла нет: иначе
    проверка расхождения не отличит «прод не знает своей версии» от «прод не
    ответил»."""
    assert "commit" in client.get("/health").json()


def test_deployed_commit_is_none_when_file_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.deployed_commit.DEPLOYED_SHA_FILE", tmp_path / "DEPLOYED_SHA")
    assert read_deployed_commit() is None


def test_deployed_commit_is_read_from_the_file(tmp_path, monkeypatch):
    sha_file = tmp_path / "DEPLOYED_SHA"
    sha_file.write_text("9da01700b64d0f5e0e9b6cbb0d8ee2b52d3a1f77\n")
    monkeypatch.setattr("app.core.deployed_commit.DEPLOYED_SHA_FILE", sha_file)
    assert read_deployed_commit() == "9da01700b64d0f5e0e9b6cbb0d8ee2b52d3a1f77"


def test_deployed_commit_ignores_a_file_that_is_not_a_sha(tmp_path, monkeypatch):
    """Обрезанный или мусорный файл не должен выглядеть как настоящая версия —
    иначе проверка расхождения будет сравнивать хеш с мусором и шуметь каждый
    день по причине, не имеющей отношения к деплою."""
    sha_file = tmp_path / "DEPLOYED_SHA"
    sha_file.write_text("не хеш")
    monkeypatch.setattr("app.core.deployed_commit.DEPLOYED_SHA_FILE", sha_file)
    assert read_deployed_commit() is None


def test_deployed_sha_file_sits_next_to_the_backend():
    """Путь выводится из расположения пакета, а не из конфигурации: файл пишет
    деплой, и лишняя переменная окружения означала бы ручной шаг на проде."""
    assert DEPLOYED_SHA_FILE.name == "DEPLOYED_SHA"
    assert DEPLOYED_SHA_FILE.parent == Path(__file__).resolve().parents[1]
