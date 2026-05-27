# 这个文件负责读取模块一运行配置和 API Key，并在缺少必要配置时提前报错。
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Mapping

import tomllib

from pydantic import BaseModel, Field, SecretStr


class MissingSettingError(RuntimeError):
    """缺少必要运行配置时抛出，主要用于 API Key 校验。"""

    pass


class Module1Settings(BaseModel):
    """模块一运行配置。

    真实密钥只存在这里或环境变量里，不会写入事件材料包。
    """

    llm_provider: str = "openai"
    llm_model: str = "gpt-4.1-mini"
    llm_base_url: str = "https://api.openai.com"
    llm_wire_api: Literal["chat_completions", "responses", "anthropic_messages"] = "chat_completions"
    model_reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = None
    disable_response_storage: bool = False
    requires_openai_auth: bool = True
    openai_api_key: SecretStr | None = None
    requires_anthropic_auth: bool = True
    anthropic_auth_token: SecretStr | None = None
    anthropic_auth_scheme: Literal["bearer", "x-api-key"] = "bearer"
    anthropic_version: str = "2023-06-01"
    llm_max_tokens: int = Field(default=2048, gt=0)
    llm_timeout_seconds: int = Field(default=120, gt=0)
    search_provider: str = "none"
    search_api_key: SecretStr | None = None
    news_feeds_path: Path = Path("configs/module1/news_feeds.yaml")
    search_results_per_query: int = Field(default=10, gt=0)
    brave_search_endpoint: str = "https://api.search.brave.com/res/v1/web/search"
    tavily_search_endpoint: str = "https://api.tavily.com/search"
    news_agent_mode: Literal["rule_based", "llm_tools"] = "rule_based"
    news_agent_max_steps: int = Field(default=6, gt=0)
    news_agent_max_tool_calls: int = Field(default=5, gt=0)
    storage_root: Path = Path("data/module1")
    user_agent: str = "HelloWorldModule1/0.1"
    http_timeout_seconds: int = Field(default=20, gt=0)
    crawl4ai_enable_stealth: bool = True
    crawl4ai_use_undetected: bool = True
    crawl4ai_headless: bool = True
    crawl4ai_max_retries: int = Field(default=1, ge=0)
    crawl4ai_profile_dir: Path | None = None
    crawl4ai_proxy: str | None = None


def _read_dotenv(path: Path) -> dict[str, str]:
    """轻量读取 .env 文件，避免第一版额外依赖 python-dotenv。"""

    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.lstrip("\ufeff").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _read_model_config(path: Path) -> dict[str, str]:
    """读取 TOML 模型配置，并转换成模块一内部使用的扁平配置键。

    兼容用户给出的这种结构：
    model_provider = "sub2api"
    [model_providers.sub2api]
    base_url = "..."
    wire_api = "responses"
    """

    if not path.exists():
        return {}

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    provider = str(data.get("model_provider", "")).strip()
    provider_configs = data.get("model_providers", {})
    provider_config = {}
    if provider and isinstance(provider_configs, dict):
        raw_provider_config = provider_configs.get(provider, {})
        if isinstance(raw_provider_config, dict):
            provider_config = raw_provider_config

    values: dict[str, str] = {}
    if provider:
        values["MODULE1_LLM_PROVIDER"] = provider
    if data.get("model") is not None:
        values["MODULE1_LLM_MODEL"] = str(data["model"])
    if data.get("model_reasoning_effort") is not None:
        values["MODULE1_MODEL_REASONING_EFFORT"] = str(data["model_reasoning_effort"])
    if data.get("disable_response_storage") is not None:
        values["MODULE1_DISABLE_RESPONSE_STORAGE"] = str(data["disable_response_storage"])
    if provider_config.get("base_url") is not None:
        values["MODULE1_LLM_BASE_URL"] = str(provider_config["base_url"])
    if provider_config.get("wire_api") is not None:
        values["MODULE1_LLM_WIRE_API"] = str(provider_config["wire_api"])
    if provider_config.get("requires_openai_auth") is not None:
        values["MODULE1_REQUIRES_OPENAI_AUTH"] = str(provider_config["requires_openai_auth"])
    if provider_config.get("requires_anthropic_auth") is not None:
        values["MODULE1_REQUIRES_ANTHROPIC_AUTH"] = str(provider_config["requires_anthropic_auth"])
    if provider_config.get("anthropic_auth_scheme") is not None:
        values["MODULE1_ANTHROPIC_AUTH_SCHEME"] = str(provider_config["anthropic_auth_scheme"])

    return values


def _as_bool(value: str | None, default: bool) -> bool:
    """把 .env/TOML 中的真假值统一转成 bool。"""

    if value is None or value == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise MissingSettingError(f"Invalid boolean value: {value}")


def _normalize_wire_api(value: str | None) -> Literal["chat_completions", "responses", "anthropic_messages"]:
    """兼容 chat、chat_completions 和 responses 三种写法。"""

    normalized = (value or "chat_completions").strip().lower().replace("-", "_")
    if normalized in {"chat", "chat_completions", "chatcompletion", "chat_completions_api"}:
        return "chat_completions"
    if normalized == "responses":
        return "responses"
    if normalized in {"anthropic", "anthropic_messages", "messages", "claude_messages"}:
        return "anthropic_messages"
    raise MissingSettingError(f"Unsupported MODULE1_LLM_WIRE_API: {value}")


def load_module1_settings(
    dotenv_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    config_path: str | Path | None = None,
    require_llm_key: bool = True,
) -> Module1Settings:
    """合并 .env、系统环境变量和测试传入的 env，生成运行配置。

    合并优先级：TOML 配置 < .env < os.environ < env 参数。测试里可以用 env 参数覆盖真实环境。
    """

    dotenv_file = Path(dotenv_path) if dotenv_path else Path(".env")
    dotenv_values = _read_dotenv(dotenv_file)

    runtime_values: dict[str, str] = {}
    runtime_values.update(os.environ)
    if env:
        runtime_values.update(dict(env))

    raw_config_path = (
        str(config_path)
        if config_path is not None
        else runtime_values.get("MODULE1_CONFIG_PATH") or dotenv_values.get("MODULE1_CONFIG_PATH")
    )

    merged: dict[str, str] = {}
    if raw_config_path:
        merged.update(_read_model_config(Path(raw_config_path)))
    merged.update(dotenv_values)
    merged.update(os.environ)
    if env:
        merged.update(dict(env))

    default_provider = "anthropic" if merged.get("ANTHROPIC_BASE_URL") or merged.get("ANTHROPIC_MODEL") else "openai"
    provider = merged.get("MODULE1_LLM_PROVIDER", default_provider).strip() or default_provider
    search_provider = merged.get("MODULE1_SEARCH_PROVIDER", "none").strip() or "none"
    default_wire_api = "anthropic_messages" if provider.lower() in {"anthropic", "claude"} else "chat_completions"
    wire_api = _normalize_wire_api(merged.get("MODULE1_LLM_WIRE_API", default_wire_api))
    base_url = (merged.get("MODULE1_LLM_BASE_URL") or merged.get("ANTHROPIC_BASE_URL") or "").strip()
    if not base_url and provider.lower() == "openai":
        base_url = "https://api.openai.com"
    if not base_url and provider.lower() in {"anthropic", "claude"}:
        base_url = "https://api.anthropic.com"
    reasoning_effort = merged.get("MODULE1_MODEL_REASONING_EFFORT") or None
    model = (
        merged.get("MODULE1_LLM_MODEL")
        or merged.get("ANTHROPIC_MODEL")
        or merged.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
        or "gpt-4.1-mini"
    )
    anthropic_auth_scheme = merged.get("MODULE1_ANTHROPIC_AUTH_SCHEME", "bearer").strip().lower()
    if anthropic_auth_scheme not in {"bearer", "x-api-key"}:
        raise MissingSettingError(f"Unsupported MODULE1_ANTHROPIC_AUTH_SCHEME: {anthropic_auth_scheme}")

    settings = Module1Settings(
        llm_provider=provider,
        llm_model=model,
        llm_base_url=base_url,
        llm_wire_api=wire_api,
        model_reasoning_effort=reasoning_effort,
        disable_response_storage=_as_bool(merged.get("MODULE1_DISABLE_RESPONSE_STORAGE"), False),
        requires_openai_auth=_as_bool(merged.get("MODULE1_REQUIRES_OPENAI_AUTH"), True),
        openai_api_key=merged.get("MODULE1_LLM_API_KEY") or merged.get("OPENAI_API_KEY") or None,
        requires_anthropic_auth=_as_bool(merged.get("MODULE1_REQUIRES_ANTHROPIC_AUTH"), True),
        anthropic_auth_token=(
            merged.get("ANTHROPIC_AUTH_TOKEN")
            or merged.get("ANTHROPIC_API_KEY")
            or merged.get("MODULE1_ANTHROPIC_API_KEY")
            or None
        ),
        anthropic_auth_scheme=anthropic_auth_scheme,
        anthropic_version=merged.get("ANTHROPIC_VERSION", "2023-06-01"),
        llm_max_tokens=int(merged.get("MODULE1_LLM_MAX_TOKENS", "2048")),
        llm_timeout_seconds=int(merged.get("MODULE1_LLM_TIMEOUT_SECONDS", "120")),
        search_provider=search_provider,
        search_api_key=merged.get("MODULE1_SEARCH_API_KEY") or None,
        news_feeds_path=Path(merged.get("MODULE1_NEWS_FEEDS_PATH", "configs/module1/news_feeds.yaml")),
        search_results_per_query=int(merged.get("MODULE1_SEARCH_RESULTS_PER_QUERY", "10")),
        brave_search_endpoint=merged.get(
            "MODULE1_BRAVE_SEARCH_ENDPOINT",
            "https://api.search.brave.com/res/v1/web/search",
        ),
        tavily_search_endpoint=merged.get(
            "MODULE1_TAVILY_SEARCH_ENDPOINT",
            "https://api.tavily.com/search",
        ),
        news_agent_mode=merged.get("MODULE1_NEWS_AGENT_MODE", "rule_based"),
        news_agent_max_steps=int(merged.get("MODULE1_NEWS_AGENT_MAX_STEPS", "6")),
        news_agent_max_tool_calls=int(merged.get("MODULE1_NEWS_AGENT_MAX_TOOL_CALLS", "5")),
        storage_root=Path(merged.get("MODULE1_STORAGE_ROOT", "data/module1")),
        user_agent=merged.get("MODULE1_USER_AGENT", "HelloWorldModule1/0.1"),
        http_timeout_seconds=int(merged.get("MODULE1_HTTP_TIMEOUT_SECONDS", "20")),
        crawl4ai_enable_stealth=_as_bool(merged.get("MODULE1_CRAWL4AI_ENABLE_STEALTH"), True),
        crawl4ai_use_undetected=_as_bool(merged.get("MODULE1_CRAWL4AI_USE_UNDETECTED"), True),
        crawl4ai_headless=_as_bool(merged.get("MODULE1_CRAWL4AI_HEADLESS"), True),
        crawl4ai_max_retries=int(merged.get("MODULE1_CRAWL4AI_MAX_RETRIES", "1")),
        crawl4ai_profile_dir=(
            Path(merged["MODULE1_CRAWL4AI_PROFILE_DIR"])
            if merged.get("MODULE1_CRAWL4AI_PROFILE_DIR")
            else None
        ),
        crawl4ai_proxy=merged.get("MODULE1_CRAWL4AI_PROXY") or None,
    )

    if require_llm_key and provider.lower() not in {"fake", "mock", "none"}:
        if not settings.llm_base_url:
            raise MissingSettingError("MODULE1_LLM_BASE_URL is required for non-openai model providers")
        if provider.lower() in {"anthropic", "claude"} and settings.requires_anthropic_auth:
            if settings.anthropic_auth_token is None:
                raise MissingSettingError(
                    "ANTHROPIC_AUTH_TOKEN, ANTHROPIC_API_KEY, or MODULE1_ANTHROPIC_API_KEY is required"
                )
        elif settings.requires_openai_auth and settings.openai_api_key is None:
            raise MissingSettingError(
                "OPENAI_API_KEY or MODULE1_LLM_API_KEY is required when MODULE1_REQUIRES_OPENAI_AUTH=true"
            )

    if search_provider.lower() not in {"none", "manual", "static", "fake", "mock", "rss"}:
        if settings.search_api_key is None:
            raise MissingSettingError("MODULE1_SEARCH_API_KEY is required for the configured search provider")

    return settings
