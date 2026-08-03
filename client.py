import json
import time
from dataclasses import dataclass
from pathlib import Path

import requests


ROOT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = ROOT_DIR / "local.json"
DEFAULT_BASE_URL = "https://api.minimaxi.com"
TRANSIENT_GET_STATUSES = {429, 500, 502, 503, 504}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


@dataclass(frozen=True)
class MiniMaxConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    poll_interval: float = 5.0
    request_timeout: int = 60
    max_wait_seconds: int = 3600


class MiniMaxAPIError(RuntimeError):
    def __init__(self, message, *, status_code=None, code=None, request_id=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id


def load_config(path=CONFIG_PATH):
    path = Path(path)
    if not path.exists():
        raise ValueError(f"Missing {path.name}. Copy local.example.json to local.json and add api_key.")

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object.")

    api_key = str(data.get("api_key") or "").strip()
    if not api_key:
        raise ValueError(f"api_key is required in {path.name}.")

    base_url = str(data.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    poll_interval = float(data.get("poll_interval", 5.0))
    request_timeout = int(data.get("request_timeout", 60))
    max_wait_seconds = int(data.get("max_wait_seconds", 3600))
    if poll_interval <= 0:
        raise ValueError("poll_interval must be greater than 0.")
    if request_timeout < 5:
        raise ValueError("request_timeout must be at least 5 seconds.")
    if max_wait_seconds <= 0:
        raise ValueError("max_wait_seconds must be greater than 0.")

    return MiniMaxConfig(
        api_key=api_key,
        base_url=base_url,
        poll_interval=poll_interval,
        request_timeout=request_timeout,
        max_wait_seconds=max_wait_seconds,
    )


class MiniMaxClient:
    def __init__(self, config, session=None, sleep=time.sleep, monotonic=time.monotonic):
        self.config = config
        self.session = session or requests.Session()
        self._owns_session = session is None
        self._sleep = sleep
        self._monotonic = monotonic
        self.session.headers.update({
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        })

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        if self._owns_session:
            self.session.close()

    def _error_from_response(self, response, payload=None):
        if payload is None:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
        detail = payload.get("error") if isinstance(payload, dict) else None
        detail = detail if isinstance(detail, dict) else {}
        message = detail.get("message") or f"MiniMax API returned HTTP {response.status_code}."
        return MiniMaxAPIError(
            message,
            status_code=response.status_code,
            code=detail.get("type") or detail.get("code"),
            request_id=payload.get("request_id") if isinstance(payload, dict) else None,
        )

    def request(self, method, path, *, json_body=None, params=None):
        method = method.upper()
        attempts = 3 if method == "GET" else 1
        url = f"{self.config.base_url}{path}"
        for attempt in range(attempts):
            try:
                response = self.session.request(
                    method,
                    url,
                    json=json_body,
                    params=params,
                    timeout=self.config.request_timeout,
                )
            except requests.Timeout as exc:
                if method == "GET" and attempt + 1 < attempts:
                    self._sleep(1.0)
                    continue
                raise TimeoutError(f"MiniMax API request timed out: {method} {path}") from exc
            except requests.RequestException as exc:
                if method == "GET" and attempt + 1 < attempts:
                    self._sleep(1.0)
                    continue
                raise ConnectionError(f"MiniMax API request failed: {method} {path}: {exc}") from exc

            if response.status_code in TRANSIENT_GET_STATUSES and method == "GET" and attempt + 1 < attempts:
                retry_after = response.headers.get("Retry-After", "1")
                try:
                    delay = max(0.0, float(retry_after))
                except ValueError:
                    delay = 1.0
                self._sleep(delay)
                continue

            try:
                payload = response.json()
            except ValueError as exc:
                raise MiniMaxAPIError(
                    f"MiniMax API returned invalid JSON (HTTP {response.status_code}).",
                    status_code=response.status_code,
                ) from exc
            if response.status_code != 200 or payload.get("type") == "error":
                raise self._error_from_response(response, payload)
            return payload

        raise RuntimeError("MiniMax API request retry loop ended unexpectedly.")

    def create_video(self, payload):
        return self.request("POST", "/v2/video_generation", json_body=payload)

    def create_context_ir(self, payload):
        return self.request("POST", "/v2/h3_context_ir", json_body=payload)

    def create_regeneration(self, payload):
        return self.request("POST", "/v2/video_regeneration", json_body=payload)

    def query_task(self, task_id):
        task_id = str(task_id or "").strip()
        if not task_id:
            raise ValueError("task_id is required.")
        return self.request("GET", f"/v2/query/video_generation/{task_id}")

    def list_tasks(self, *, page_num=1, page_size=20, status="", task_ids=None, model="", task_type=""):
        params = {"page_num": int(page_num), "page_size": int(page_size)}
        if status:
            params["filter.status"] = status
        if task_ids:
            params["filter.task_ids"] = list(task_ids)
        if model:
            params["filter.model"] = model
        if task_type:
            params["filter.task_type"] = task_type
        return self.request("GET", "/v2/query/video_generation", params=params)

    def delete_task(self, task_id):
        task_id = str(task_id or "").strip()
        if not task_id:
            raise ValueError("task_id is required.")
        return self.request("DELETE", f"/v2/video_generation/{task_id}")

    def wait_task(self, task_id):
        start = self._monotonic()
        last_status = None
        while True:
            payload = self.query_task(task_id)
            task = payload.get("task") or {}
            status = task.get("status")
            if status != last_status:
                print(f"[MiniMax H3] task_id={task_id} status={status or 'unknown'}")
                last_status = status
            if status in TERMINAL_STATUSES:
                if status == "succeeded":
                    return payload
                error = task.get("error") or {}
                message = error.get("message") or f"MiniMax task {task_id} ended with status={status}."
                raise MiniMaxAPIError(message, code=error.get("code"))
            if self._monotonic() - start >= self.config.max_wait_seconds:
                raise TimeoutError(f"MiniMax task {task_id} did not finish within {self.config.max_wait_seconds} seconds.")
            self._sleep(self.config.poll_interval)
