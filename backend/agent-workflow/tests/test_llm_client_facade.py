from types import SimpleNamespace

from kardcraft.llm.client import LLMContextError, aembedding, arerank, chat_complete
from kardcraft.llm.context import LLMRuntimeContext, reset_runtime_context, set_runtime_context


class _FakeResponse:
    def __init__(self, *, response_id: str = "resp-1", prompt_tokens: int = 10, completion_tokens: int = 5):
        self.id = response_id
        self.usage = SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        self.choices = [SimpleNamespace(message=SimpleNamespace(content="ok"))]


async def test_llm_client_requires_runtime_context(monkeypatch):
    async def _fake_completion(**_: object):
        return _FakeResponse()

    monkeypatch.setattr("kardcraft.llm.client.litellm.acompletion", _fake_completion)
    monkeypatch.setattr(
        "kardcraft.llm.client.get_completion_config",
        lambda **_: {"model": "openai/gpt-4o-mini", "temperature": 0.1},
    )

    try:
        await chat_complete(messages=[{"role": "user", "content": "hello"}], intent="chat")
        assert False, "expected LLMContextError"
    except LLMContextError:
        pass


async def test_llm_client_emits_usage_payload(monkeypatch):
    emitted: list[dict[str, object]] = []

    async def _fake_completion(**_: object):
        return _FakeResponse(response_id="req-123", prompt_tokens=8, completion_tokens=4)

    async def _emit(payload: dict[str, object]) -> None:
        emitted.append(payload)

    token = set_runtime_context(
        LLMRuntimeContext(
            task_id="task-1",
            session_id="session-1",
            user_id="user-1",
            usage_emitter=_emit,
        )
    )
    monkeypatch.setattr("kardcraft.llm.client.litellm.acompletion", _fake_completion)
    monkeypatch.setattr(
        "kardcraft.llm.client.get_completion_config",
        lambda **_: {"model": "openai/gpt-4o-mini", "temperature": 0.1},
    )

    try:
        resp = await chat_complete(messages=[{"role": "user", "content": "hello"}], intent="chat")
        assert resp.id == "req-123"
    finally:
        reset_runtime_context(token)

    assert len(emitted) == 1
    payload = emitted[0]
    assert payload["schema_version"] == "1"
    assert payload["task_id"] == "task-1"
    assert payload["session_id"] == "session-1"
    assert payload["user_id"] == "user-1"
    assert payload["provider"] == "openai"
    assert payload["model"] == "openai/gpt-4o-mini"
    assert payload["prompt_tokens"] == 8
    assert payload["completion_tokens"] == 4
    assert payload["total_tokens"] == 12
    assert payload["estimated"] is False
    assert str(payload["idempotency_key"]).startswith("task-1:req-123")


async def test_llm_client_retries_transient_failure(monkeypatch):
    calls = {"n": 0}
    emitted: list[dict[str, object]] = []

    async def _fake_completion(**_: object):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("transient timeout")
        return _FakeResponse(response_id="req-456")

    async def _emit(payload: dict[str, object]) -> None:
        emitted.append(payload)

    token = set_runtime_context(
        LLMRuntimeContext(
            task_id="task-2",
            session_id="session-2",
            user_id="user-2",
            usage_emitter=_emit,
        )
    )
    monkeypatch.setattr("kardcraft.llm.client.litellm.acompletion", _fake_completion)
    monkeypatch.setattr(
        "kardcraft.llm.client.get_completion_config",
        lambda **_: {"model": "openai/gpt-4o-mini", "temperature": 0.1},
    )

    try:
        await chat_complete(
            messages=[{"role": "user", "content": "hello"}],
            intent="chat",
            max_attempts=2,
            retry_delay_seconds=0.0,
        )
    finally:
        reset_runtime_context(token)

    assert calls["n"] == 2
    assert len(emitted) == 1


async def test_llm_client_embedding_emits_usage(monkeypatch):
    emitted: list[dict[str, object]] = []

    async def _fake_embedding(**_: object):
        return _FakeResponse(response_id="emb-1", prompt_tokens=6, completion_tokens=0)

    async def _emit(payload: dict[str, object]) -> None:
        emitted.append(payload)

    token = set_runtime_context(
        LLMRuntimeContext(
            task_id="task-emb",
            session_id="session-emb",
            user_id="user-emb",
            usage_emitter=_emit,
        )
    )
    monkeypatch.setattr("kardcraft.llm.client.litellm.aembedding", _fake_embedding)
    monkeypatch.setattr("kardcraft.llm.client.get_embed_model", lambda: "openai/text-embedding-3-small")
    try:
        await aembedding(input="hello embedding")
    finally:
        reset_runtime_context(token)

    assert len(emitted) == 1
    assert emitted[0]["operation"] == "aembedding"
    assert emitted[0]["intent"] == "embedding"


async def test_llm_client_rerank_emits_usage(monkeypatch):
    emitted: list[dict[str, object]] = []

    async def _fake_rerank(**_: object):
        return _FakeResponse(response_id="rr-1", prompt_tokens=12, completion_tokens=0)

    async def _emit(payload: dict[str, object]) -> None:
        emitted.append(payload)

    token = set_runtime_context(
        LLMRuntimeContext(
            task_id="task-rr",
            session_id="session-rr",
            user_id="user-rr",
            usage_emitter=_emit,
        )
    )
    monkeypatch.setattr("kardcraft.llm.client.litellm.arerank", _fake_rerank)
    monkeypatch.setattr("kardcraft.llm.client.get_rerank_model", lambda: "cohere/rerank-english-v3.0")
    try:
        await arerank(query="q", documents=["d1", "d2"])
    finally:
        reset_runtime_context(token)

    assert len(emitted) == 1
    assert emitted[0]["operation"] == "arerank"
    assert emitted[0]["intent"] == "rerank"
