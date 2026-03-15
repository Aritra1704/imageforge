from fastapi.testclient import TestClient

from app.main import create_app


def test_health_route(client):
    response = client.get("/health", headers={"X-Request-Id": "health-test"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["service"] == "imageforge"
    assert body["busy"] is False
    assert body["comfyui_reachable"] is True
    assert body["database_reachable"] is True
    assert body["storage_reachable"] is True
    assert body["provider"] == "comfyui"
    assert body["request_id"] == "health-test"
    assert response.headers["X-Request-Id"] == "health-test"


def test_ready_route_success(client):
    response = client.get("/ready", headers={"X-Request-Id": "ready-test"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["service"] == "imageforge"
    assert body["checks"]["database_reachable"] is True
    assert body["checks"]["schema_ready"] is True
    assert body["checks"]["storage_reachable"] is True
    assert body["checks"]["comfyui_reachable"] is True
    assert body["checks"]["workflow_present"] is True
    assert body["request_id"] == "ready-test"


def test_ready_fails_when_workflow_missing(settings, repository, storage, providers):
    missing_settings = settings.model_copy(
        update={"comfyui_workflow_path": storage.root / "missing_workflow.json"}
    )
    app = create_app(
        settings=missing_settings,
        repository=repository,
        storage=storage,
        providers=providers,
    )
    response = TestClient(app).get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    assert body["checks"]["workflow_present"] is False
