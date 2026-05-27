# 这个测试文件验证模型客户端的假实现能稳定返回文本和结构化 JSON。
import json
from urllib.request import Request

from pydantic import BaseModel

from module1.llm.agent_client import (
    AnthropicMessagesAgentClient,
    FakeAgentClient,
    OpenAIResponsesAgentClient,
    build_agent_client,
)
from module1.settings import Module1Settings


class ResponseModel(BaseModel):
    ok: bool
    value: str


def test_fake_agent_client_returns_text_and_json():
    client = FakeAgentClient(
        text_responses=["hello"],
        json_responses=[{"ok": True, "value": "ready"}],
    )

    assert client.chat_text([{"role": "user", "content": "ping"}]) == "hello"
    response = client.chat_json([{"role": "user", "content": "json"}], ResponseModel)

    assert response.ok is True
    assert response.value == "ready"
    assert len(client.calls) == 2


def test_build_agent_client_supports_sub2api_responses():
    settings = Module1Settings(
        llm_provider="sub2api",
        llm_model="gpt-5.4",
        llm_base_url="http://example.test",
        llm_wire_api="responses",
        openai_api_key="test-key",
    )

    assert isinstance(build_agent_client(settings), OpenAIResponsesAgentClient)


def test_responses_client_posts_to_custom_base_url(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps({"output_text": "hello from sub2api"}).encode("utf-8")

    def fake_urlopen(request: Request, timeout: int):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    settings = Module1Settings(
        llm_provider="sub2api",
        llm_model="gpt-5.4",
        llm_base_url="http://110.42.53.85:11098",
        llm_wire_api="responses",
        model_reasoning_effort="high",
        disable_response_storage=True,
        openai_api_key="test-key",
        http_timeout_seconds=9,
        llm_timeout_seconds=45,
    )
    client = OpenAIResponsesAgentClient(settings)

    text = client.chat_text([{"role": "user", "content": "ping"}])

    assert text == "hello from sub2api"
    assert captured["url"] == "http://110.42.53.85:11098/v1/responses"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["payload"]["model"] == "gpt-5.4"
    assert captured["payload"]["reasoning"] == {"effort": "high"}
    assert captured["payload"]["store"] is False
    assert captured["payload"]["input"][0]["content"][0]["text"] == "ping"
    assert captured["timeout"] == 45


def test_build_agent_client_supports_anthropic_messages():
    settings = Module1Settings(
        llm_provider="anthropic",
        llm_model="glm-5.1",
        llm_base_url="http://example.test",
        llm_wire_api="anthropic_messages",
        anthropic_auth_token="test-token",
    )

    assert isinstance(build_agent_client(settings), AnthropicMessagesAgentClient)


def test_anthropic_client_posts_to_custom_base_url(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps({"content": [{"type": "text", "text": "OK"}]}).encode("utf-8")

    def fake_urlopen(request: Request, timeout: int):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    settings = Module1Settings(
        llm_provider="anthropic",
        llm_model="glm-5.1",
        llm_base_url="http://110.42.53.85:11098",
        llm_wire_api="anthropic_messages",
        anthropic_auth_token="test-token",
        anthropic_auth_scheme="bearer",
        llm_max_tokens=123,
        http_timeout_seconds=7,
        llm_timeout_seconds=60,
    )
    client = AnthropicMessagesAgentClient(settings)

    text = client.chat_text(
        [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "ping"},
        ]
    )

    assert text == "OK"
    assert captured["url"] == "http://110.42.53.85:11098/v1/messages"
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert captured["headers"]["Anthropic-version"] == "2023-06-01"
    assert captured["payload"]["model"] == "glm-5.1"
    assert captured["payload"]["max_tokens"] == 123
    assert captured["payload"]["system"] == "You are concise."
    assert captured["payload"]["messages"] == [{"role": "user", "content": "ping"}]
    assert captured["timeout"] == 60
