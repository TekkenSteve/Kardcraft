from kardcraft.sandbox_broker.safe_fetch import SafeFetchPolicy, safe_fetch


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class _FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None):
        return _FakeResponse(200, text="hello")


class _RedirectClient:
    def __init__(self, *args, **kwargs):
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None):
        self.calls += 1
        if self.calls == 1:
            return _FakeResponse(302, headers={"Location": "https://example.com/next"})
        return _FakeResponse(200, text="redirect-ok")


class _LoopRedirectClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None):
        return _FakeResponse(302, headers={"Location": "https://example.com/loop"})


class _OversizeClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None):
        return _FakeResponse(200, text="x" * (1024 * 1024 + 10))


async def test_safe_fetch_allows_https_public_host(monkeypatch):
    async def _resolve(host: str):
        return ["93.184.216.34"]

    monkeypatch.setattr("kardcraft.sandbox_broker.safe_fetch._resolve_ips", _resolve)
    monkeypatch.setattr("kardcraft.sandbox_broker.safe_fetch.httpx.AsyncClient", _FakeClient)

    content = await safe_fetch(
        "https://example.com",
        policy=SafeFetchPolicy(allow_hosts=("example.com",)),
    )
    assert content == "hello"


async def test_safe_fetch_rejects_http_scheme():
    try:
        await safe_fetch(
            "http://example.com",
            policy=SafeFetchPolicy(allow_hosts=("example.com",)),
        )
        assert False, "expected scheme denied"
    except Exception as exc:
        assert "SAFE_FETCH_SCHEME_DENIED" in str(exc) or "scheme denied" in str(exc)


async def test_safe_fetch_rejects_non_allowlisted_host():
    try:
        await safe_fetch(
            "https://evil.com",
            policy=SafeFetchPolicy(allow_hosts=("example.com",)),
        )
        assert False, "expected host denied"
    except Exception as exc:
        assert "SAFE_FETCH_HOST_DENIED" in str(exc) or "host not allowed" in str(exc)


async def test_safe_fetch_rejects_private_ip_resolution(monkeypatch):
    async def _resolve(host: str):
        return ["127.0.0.1"]

    monkeypatch.setattr("kardcraft.sandbox_broker.safe_fetch._resolve_ips", _resolve)
    monkeypatch.setattr("kardcraft.sandbox_broker.safe_fetch.httpx.AsyncClient", _FakeClient)
    try:
        await safe_fetch(
            "https://example.com",
            policy=SafeFetchPolicy(allow_hosts=("example.com",)),
        )
        assert False, "expected private ip denied"
    except Exception as exc:
        assert "SAFE_FETCH_IP_PRIVATE_DENIED" in str(exc) or "forbidden ip" in str(exc)


async def test_safe_fetch_redirect_revalidated(monkeypatch):
    async def _resolve(host: str):
        return ["93.184.216.34"]

    monkeypatch.setattr("kardcraft.sandbox_broker.safe_fetch._resolve_ips", _resolve)
    monkeypatch.setattr("kardcraft.sandbox_broker.safe_fetch.httpx.AsyncClient", _RedirectClient)
    content = await safe_fetch(
        "https://example.com/start",
        policy=SafeFetchPolicy(allow_hosts=("example.com",)),
    )
    assert content == "redirect-ok"


async def test_safe_fetch_rejects_redirect_loop(monkeypatch):
    async def _resolve(host: str):
        return ["93.184.216.34"]

    monkeypatch.setattr("kardcraft.sandbox_broker.safe_fetch._resolve_ips", _resolve)
    monkeypatch.setattr("kardcraft.sandbox_broker.safe_fetch.httpx.AsyncClient", _LoopRedirectClient)
    try:
        await safe_fetch(
            "https://example.com/start",
            policy=SafeFetchPolicy(allow_hosts=("example.com",), max_redirects=1),
        )
        assert False, "expected redirect denied"
    except Exception as exc:
        assert getattr(exc, "code", "") == "SAFE_FETCH_REDIRECT_DENIED"


async def test_safe_fetch_rejects_oversize_content(monkeypatch):
    async def _resolve(host: str):
        return ["93.184.216.34"]

    monkeypatch.setattr("kardcraft.sandbox_broker.safe_fetch._resolve_ips", _resolve)
    monkeypatch.setattr("kardcraft.sandbox_broker.safe_fetch.httpx.AsyncClient", _OversizeClient)
    try:
        await safe_fetch(
            "https://example.com",
            policy=SafeFetchPolicy(allow_hosts=("example.com",), max_bytes=32),
        )
        assert False, "expected content too large"
    except Exception as exc:
        assert getattr(exc, "code", "") == "SAFE_FETCH_CONTENT_TOO_LARGE"
