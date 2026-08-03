import json

import pytest

import minimax_test_client as client


class FakeResponse:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def config(**overrides):
    values = {"api_key": "secret", "poll_interval": 0.01, "request_timeout": 10, "max_wait_seconds": 10}
    values.update(overrides)
    return client.MiniMaxConfig(**values)


def test_load_config(tmp_path):
    path = tmp_path / "local.json"
    path.write_text(json.dumps({"api_key": " key ", "poll_interval": 2}), encoding="utf-8")
    loaded = client.load_config(path)
    assert loaded.api_key == "key"
    assert loaded.poll_interval == 2
    assert loaded.base_url == client.DEFAULT_BASE_URL


def test_load_config_requires_key(tmp_path):
    path = tmp_path / "local.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="api_key"):
        client.load_config(path)


def test_create_uses_bearer_and_does_not_retry():
    session = FakeSession([FakeResponse(200, {"task_id": "123"})])
    api = client.MiniMaxClient(config(), session=session)
    assert api.create_video({"model": "MiniMax-H3"}) == {"task_id": "123"}
    assert session.headers["Authorization"] == "Bearer secret"
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url.endswith("/v2/video_generation")
    assert kwargs["json"] == {"model": "MiniMax-H3"}


def test_get_retries_transient_status():
    session = FakeSession([
        FakeResponse(429, {"type": "error", "error": {"message": "slow"}}, {"Retry-After": "0"}),
        FakeResponse(200, {"task": {"id": "123", "status": "running"}}),
    ])
    api = client.MiniMaxClient(config(), session=session, sleep=lambda _: None)
    result = api.query_task("123")
    assert result["task"]["status"] == "running"
    assert len(session.calls) == 2


def test_wait_task_returns_success_and_logs_status_changes(capsys):
    session = FakeSession([
        FakeResponse(200, {"task": {"id": "123", "status": "queued"}}),
        FakeResponse(200, {"task": {"id": "123", "status": "queued"}}),
        FakeResponse(200, {"task": {"id": "123", "status": "running"}}),
        FakeResponse(200, {"task": {"id": "123", "status": "succeeded", "content": {"url": "https://cdn/video.mp4"}}}),
    ])
    api = client.MiniMaxClient(config(), session=session, sleep=lambda _: None)
    result = api.wait_task("123")
    assert result["task"]["content"]["url"].endswith("video.mp4")
    assert capsys.readouterr().out.splitlines() == [
        "[MiniMax H3] task_id=123 status=queued",
        "[MiniMax H3] task_id=123 status=running",
        "[MiniMax H3] task_id=123 status=succeeded",
    ]


def test_wait_task_raises_task_error(capsys):
    session = FakeSession([
        FakeResponse(200, {"task": {"id": "123", "status": "failed", "error": {"code": "1026", "message": "sensitive"}}}),
    ])
    api = client.MiniMaxClient(config(), session=session)
    with pytest.raises(client.MiniMaxAPIError, match="sensitive") as exc_info:
        api.wait_task("123")
    assert exc_info.value.code == "1026"
    assert capsys.readouterr().out.strip() == "[MiniMax H3] task_id=123 status=failed"


def test_api_error_includes_request_id():
    session = FakeSession([
        FakeResponse(401, {"type": "error", "error": {"type": "authorized_error", "message": "bad key"}, "request_id": "req-1"}),
    ])
    api = client.MiniMaxClient(config(), session=session)
    with pytest.raises(client.MiniMaxAPIError) as exc_info:
        api.create_video({})
    assert exc_info.value.status_code == 401
    assert exc_info.value.request_id == "req-1"


def test_list_builds_filters():
    session = FakeSession([FakeResponse(200, {"items": [], "total": 0})])
    api = client.MiniMaxClient(config(), session=session)
    api.list_tasks(status="succeeded", task_ids=["1", "2"], model="MiniMax-H3", task_type="generation")
    params = session.calls[0][2]["params"]
    assert params["filter.task_ids"] == ["1", "2"]
    assert params["filter.status"] == "succeeded"
