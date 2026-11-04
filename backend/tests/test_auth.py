"""Auth tests."""
from fastapi.testclient import TestClient


def test_health(client: TestClient):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_dashboard_redirects_when_not_logged_in(client: TestClient):
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/login")


def test_login_bad_credentials(client: TestClient):
    resp = client.post("/api/v1/login", data={"username": "admin", "password": "wrong"}, follow_redirects=False)
    assert resp.status_code == 302
    assert "error=" in resp.headers["location"]
