# 这个测试文件验证前端工作台服务能返回首页，并能启动一次模块一运行。
from fastapi.testclient import TestClient

from module1.web_app import app


def test_web_app_serves_index():
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "事件采集 Agent" in response.text


def test_web_app_starts_run(monkeypatch):
    monkeypatch.setattr("module1.web_app.load_module1_settings", lambda: _fake_settings())
    client = TestClient(app)

    response = client.post("/api/runs", json={"message": "test event"})

    assert response.status_code == 200
    assert response.json()["run_id"].startswith("run_")


def _fake_settings():
    from module1.settings import Module1Settings

    return Module1Settings(
        llm_provider="fake",
        search_provider="none",
        storage_root="tmp/tests/web_app/data",
    )
