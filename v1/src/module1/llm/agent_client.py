# 这个文件封装模型调用接口；支持 OpenAI-compatible 和 Anthropic/Claude-compatible 第三方网关。
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Protocol

from pydantic import BaseModel

from module1.settings import Module1Settings


class AgentClient(Protocol):
    """所有 Agent 调用大模型时依赖的统一接口。

    业务代码只依赖这个协议，因此测试时可以替换成 FakeAgentClient。
    """

    def chat_text(self, messages: list[dict]) -> str:
        ...

    def chat_json(self, messages: list[dict], schema: type[BaseModel]) -> BaseModel:
        ...


class FakeAgentClient:
    """测试用假客户端，不联网、不消耗真实 API。

    text_responses 和 json_responses 会按顺序弹出，方便精确测试 Agent 行为。
    """

    def __init__(
        self,
        text_responses: list[str] | None = None,
        json_responses: list[dict | str | BaseModel] | None = None,
    ) -> None:
        self.text_responses = list(text_responses or [])
        self.json_responses = list(json_responses or [])
        self.calls: list[list[dict]] = []

    def chat_text(self, messages: list[dict]) -> str:
        self.calls.append(messages)
        if self.text_responses:
            return self.text_responses.pop(0)
        if messages:
            return str(messages[-1].get("content", ""))
        return ""

    def chat_json(self, messages: list[dict], schema: type[BaseModel]) -> BaseModel:
        self.calls.append(messages)
        if not self.json_responses:
            raise RuntimeError("FakeAgentClient has no queued JSON response")

        response = self.json_responses.pop(0)
        if isinstance(response, schema):
            return response
        if isinstance(response, BaseModel):
            return schema.model_validate(response.model_dump())
        if isinstance(response, str):
            return schema.model_validate_json(response)
        return schema.model_validate(response)


class OpenAIChatCompletionsAgentClient:
    """OpenAI Chat Completions 兼容的最小文本/JSON 调用客户端。

    既可请求官方 OpenAI，也可请求支持 /v1/chat/completions 的第三方网关。
    """

    def __init__(self, settings: Module1Settings) -> None:
        if settings.requires_openai_auth and settings.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY or MODULE1_LLM_API_KEY is required")
        self.model = settings.llm_model
        self.api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        self.endpoint = _join_api_url(settings.llm_base_url, "/v1/chat/completions")
        self.timeout = settings.llm_timeout_seconds

    def chat_text(self, messages: list[dict]) -> str:
        data = self._post_chat(messages)
        return data["choices"][0]["message"]["content"]

    def chat_json(self, messages: list[dict], schema: type[BaseModel]) -> BaseModel:
        # 这里要求模型只返回 JSON，然后再交给 Pydantic 做结构校验。
        guarded = [
            {
                "role": "system",
                "content": "Return only valid JSON matching the requested schema.",
            },
            *messages,
        ]
        text = self.chat_text(guarded)
        return schema.model_validate_json(text)

    def _post_chat(self, messages: list[dict]) -> dict:
        """实际发起 HTTP 请求。

        错误信息只暴露状态码和 request_id，不把 API Key 写到异常里。
        """

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
        }
        return _post_json(self.endpoint, payload, self.api_key, self.timeout)


class OpenAIResponsesAgentClient:
    """OpenAI Responses API 兼容客户端。

    这个实现用于 wire_api="responses" 的官方 OpenAI 或第三方兼容服务，例如 sub2api。
    """

    def __init__(self, settings: Module1Settings) -> None:
        if settings.requires_openai_auth and settings.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY or MODULE1_LLM_API_KEY is required")
        self.model = settings.llm_model
        self.api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        self.endpoint = _join_api_url(settings.llm_base_url, "/v1/responses")
        self.timeout = settings.llm_timeout_seconds
        self.reasoning_effort = settings.model_reasoning_effort
        self.store = not settings.disable_response_storage

    def chat_text(self, messages: list[dict]) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": _messages_to_response_input(messages),
            "store": self.store,
        }
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}

        data = _post_json(self.endpoint, payload, self.api_key, self.timeout)
        return _extract_response_text(data)

    def chat_json(self, messages: list[dict], schema: type[BaseModel]) -> BaseModel:
        # 先用 prompt 约束返回 JSON，再由 Pydantic 做最终格式校验；这样对第三方兼容网关更稳。
        guarded = [
            {
                "role": "system",
                "content": "Return only valid JSON matching the requested schema.",
            },
            *messages,
        ]
        text = self.chat_text(guarded)
        return schema.model_validate_json(text)


class AnthropicMessagesAgentClient:
    """Anthropic Messages API 兼容客户端。

    用于 Claude/Anthropic 格式的第三方网关，请求路径是 /v1/messages。
    """

    def __init__(self, settings: Module1Settings) -> None:
        if settings.requires_anthropic_auth and settings.anthropic_auth_token is None:
            raise ValueError("ANTHROPIC_AUTH_TOKEN, ANTHROPIC_API_KEY, or MODULE1_ANTHROPIC_API_KEY is required")
        self.model = settings.llm_model
        self.auth_token = (
            settings.anthropic_auth_token.get_secret_value() if settings.anthropic_auth_token else None
        )
        self.auth_scheme = settings.anthropic_auth_scheme
        self.anthropic_version = settings.anthropic_version
        self.endpoint = _join_api_url(settings.llm_base_url, "/v1/messages")
        self.timeout = settings.llm_timeout_seconds
        self.max_tokens = settings.llm_max_tokens

    def chat_text(self, messages: list[dict]) -> str:
        system_prompt, anthropic_messages = _messages_to_anthropic_payload(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": anthropic_messages,
        }
        if system_prompt:
            payload["system"] = system_prompt

        data = _post_anthropic_json(
            self.endpoint,
            payload,
            self.auth_token,
            self.auth_scheme,
            self.anthropic_version,
            self.timeout,
        )
        return _extract_anthropic_text(data)

    def chat_json(self, messages: list[dict], schema: type[BaseModel]) -> BaseModel:
        # Anthropic Messages API 没有统一 JSON mode，这里仍然用 prompt 约束，再用 Pydantic 严格校验。
        guarded = [
            {
                "role": "system",
                "content": "Return only valid JSON matching the requested schema.",
            },
            *messages,
        ]
        text = self.chat_text(guarded)
        return schema.model_validate_json(text)


OpenAIAgentClient = OpenAIChatCompletionsAgentClient


def _join_api_url(base_url: str, api_path: str) -> str:
    """拼接 base_url 和 API 路径，避免 base_url 已包含 /v1 时重复拼接。"""

    base = base_url.rstrip("/")
    if base.endswith("/v1") and api_path.startswith("/v1/"):
        return f"{base}{api_path[3:]}"
    return f"{base}{api_path}"


def _messages_to_response_input(messages: list[dict]) -> list[dict]:
    """把 Chat Completions 风格 messages 转成 Responses API 的 input items。"""

    response_input: list[dict] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = message.get("content", "")
        if isinstance(content, list):
            text = "\n".join(str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in content)
        else:
            text = str(content)
        response_input.append(
            {
                "role": role,
                "content": [
                    {
                        "type": "input_text",
                        "text": text,
                    }
                ],
            }
        )
    return response_input


def _messages_to_anthropic_payload(messages: list[dict]) -> tuple[str | None, list[dict]]:
    """把通用 messages 转成 Anthropic Messages API 的 system + messages 结构。"""

    system_parts: list[str] = []
    anthropic_messages: list[dict] = []
    for message in messages:
        role = str(message.get("role", "user"))
        text = _message_content_to_text(message.get("content", ""))
        if role in {"system", "developer"}:
            system_parts.append(text)
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        anthropic_messages.append({"role": role, "content": text})

    if not anthropic_messages:
        anthropic_messages.append({"role": "user", "content": ""})
    return ("\n\n".join(part for part in system_parts if part) or None, anthropic_messages)


def _message_content_to_text(content: object) -> str:
    """把各种简化消息内容压成纯文本，满足 v1 文本任务的最小需要。"""

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", item)))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _extract_response_text(data: dict) -> str:
    """从 Responses API 返回体中提取文本，兼容官方格式和部分第三方简化格式。"""

    if isinstance(data.get("output_text"), str):
        return data["output_text"]

    texts: list[str] = []
    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        for content_item in item.get("content", []):
            if not isinstance(content_item, dict):
                continue
            if content_item.get("type") in {"output_text", "text"} and isinstance(content_item.get("text"), str):
                texts.append(content_item["text"])
    if texts:
        return "\n".join(texts)

    choices = data.get("choices", [])
    if choices:
        message = choices[0].get("message", {})
        if isinstance(message.get("content"), str):
            return message["content"]

    response_id = data.get("id", "unknown")
    status = data.get("status", "unknown")
    raise RuntimeError(f"Responses API returned no text output: id={response_id}, status={status}")


def _extract_anthropic_text(data: dict) -> str:
    """从 Anthropic Messages API 返回体中提取文本。"""

    texts: list[str] = []
    for content_item in data.get("content", []):
        if not isinstance(content_item, dict):
            continue
        if content_item.get("type") == "text" and isinstance(content_item.get("text"), str):
            texts.append(content_item["text"])
    if texts:
        return "\n".join(texts)

    response_id = data.get("id", "unknown")
    stop_reason = data.get("stop_reason", "unknown")
    raise RuntimeError(f"Anthropic Messages API returned no text output: id={response_id}, stop_reason={stop_reason}")


def _post_json(endpoint: str, payload: dict, api_key: str | None, timeout: int) -> dict:
    """发起 JSON HTTP 请求，错误信息不包含密钥。"""

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        request_id = exc.headers.get("x-request-id") or exc.headers.get("request-id") or "unknown"
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(
            f"LLM API request failed: endpoint={endpoint}, status={exc.code}, request_id={request_id}, body={body}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"LLM API request failed: endpoint={endpoint}, error={exc}") from exc


def _post_anthropic_json(
    endpoint: str,
    payload: dict,
    auth_token: str | None,
    auth_scheme: str,
    anthropic_version: str,
    timeout: int,
) -> dict:
    """发起 Anthropic 风格 JSON 请求，支持 Bearer token 或 x-api-key。"""

    headers = {
        "Content-Type": "application/json",
        "anthropic-version": anthropic_version,
    }
    if auth_token and auth_scheme == "bearer":
        headers["Authorization"] = f"Bearer {auth_token}"
    elif auth_token:
        headers["x-api-key"] = auth_token

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        request_id = exc.headers.get("request-id") or exc.headers.get("x-request-id") or "unknown"
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(
            f"Anthropic API request failed: endpoint={endpoint}, status={exc.code}, request_id={request_id}, body={body}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Anthropic API request failed: endpoint={endpoint}, error={exc}") from exc


def build_agent_client(settings: Module1Settings) -> AgentClient:
    """根据 settings 选择真实客户端或测试客户端。"""

    provider = settings.llm_provider.lower()
    if provider in {"fake", "mock", "none"}:
        return FakeAgentClient()
    if provider in {"anthropic", "claude"} or settings.llm_wire_api == "anthropic_messages":
        return AnthropicMessagesAgentClient(settings)
    if settings.llm_wire_api == "responses":
        return OpenAIResponsesAgentClient(settings)
    if settings.llm_wire_api == "chat_completions":
        return OpenAIChatCompletionsAgentClient(settings)
    raise ValueError(f"Unsupported MODULE1_LLM_PROVIDER: {settings.llm_provider}")
