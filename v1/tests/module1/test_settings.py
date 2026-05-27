# 这个测试文件验证配置读取逻辑，尤其是 fake provider 和 OpenAI API Key 校验。
from pathlib import Path
from uuid import uuid4

import pytest

from module1.settings import MissingSettingError, load_module1_settings


def test_settings_allow_fake_provider_without_key():
    settings = load_module1_settings(
        dotenv_path="tmp/tests/settings/.env",
        env={
            "MODULE1_LLM_PROVIDER": "fake",
            "MODULE1_STORAGE_ROOT": "tmp/tests/settings/data",
        },
    )

    assert settings.llm_provider == "fake"
    assert settings.openai_api_key is None
    assert str(settings.storage_root).replace("\\", "/") == "tmp/tests/settings/data"


def test_settings_require_openai_key():
    with pytest.raises(MissingSettingError):
        load_module1_settings(
            dotenv_path="tmp/tests/settings/.env",
            env={
                "MODULE1_LLM_PROVIDER": "openai",
                "OPENAI_API_KEY": "",
            },
        )


def test_settings_load_sub2api_responses_from_env():
    settings = load_module1_settings(
        dotenv_path="tmp/tests/settings/.env",
        env={
            "MODULE1_LLM_PROVIDER": "sub2api",
            "MODULE1_LLM_MODEL": "gpt-5.4",
            "MODULE1_LLM_BASE_URL": "http://110.42.53.85:11098",
            "MODULE1_LLM_WIRE_API": "responses",
            "MODULE1_MODEL_REASONING_EFFORT": "high",
            "MODULE1_DISABLE_RESPONSE_STORAGE": "true",
            "OPENAI_API_KEY": "test-key",
        },
    )

    assert settings.llm_provider == "sub2api"
    assert settings.llm_model == "gpt-5.4"
    assert settings.llm_base_url == "http://110.42.53.85:11098"
    assert settings.llm_wire_api == "responses"
    assert settings.model_reasoning_effort == "high"
    assert settings.disable_response_storage is True


def test_settings_load_anthropic_format_env():
    settings = load_module1_settings(
        dotenv_path="tmp/tests/settings/.env",
        env={
            "MODULE1_LLM_PROVIDER": "anthropic",
            "ANTHROPIC_AUTH_TOKEN": "test-token",
            "ANTHROPIC_BASE_URL": "http://110.42.53.85:11098",
            "ANTHROPIC_MODEL": "glm-5.1",
            "ANTHROPIC_REASONING_MODEL": "glm-5.1",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "glm-5.1",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "glm-5.1",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-5.1",
        },
    )

    assert settings.llm_provider == "anthropic"
    assert settings.llm_model == "glm-5.1"
    assert settings.llm_base_url == "http://110.42.53.85:11098"
    assert settings.llm_wire_api == "anthropic_messages"
    assert settings.anthropic_auth_token is not None
    assert settings.anthropic_auth_scheme == "bearer"


def test_settings_infer_anthropic_provider_from_anthropic_env():
    settings = load_module1_settings(
        dotenv_path="tmp/tests/settings/.env",
        env={
            "ANTHROPIC_AUTH_TOKEN": "test-token",
            "ANTHROPIC_BASE_URL": "http://110.42.53.85:11098",
            "ANTHROPIC_MODEL": "glm-5.1",
        },
    )

    assert settings.llm_provider == "anthropic"
    assert settings.llm_wire_api == "anthropic_messages"


def test_settings_allow_separate_llm_and_http_timeouts():
    settings = load_module1_settings(
        dotenv_path="tmp/tests/settings/.env",
        env={
            "MODULE1_LLM_PROVIDER": "fake",
            "MODULE1_HTTP_TIMEOUT_SECONDS": "5",
            "MODULE1_LLM_TIMEOUT_SECONDS": "90",
        },
    )

    assert settings.http_timeout_seconds == 5
    assert settings.llm_timeout_seconds == 90


def test_settings_require_search_key_for_web_search():
    with pytest.raises(MissingSettingError):
        load_module1_settings(
            dotenv_path="tmp/tests/settings/.env",
            env={
                "MODULE1_LLM_PROVIDER": "fake",
                "MODULE1_SEARCH_PROVIDER": "web_search",
                "MODULE1_SEARCH_API_KEY": "",
            },
        )


def test_settings_load_web_search_provider_with_key():
    settings = load_module1_settings(
        dotenv_path="tmp/tests/settings/.env",
        env={
            "MODULE1_LLM_PROVIDER": "fake",
            "MODULE1_SEARCH_PROVIDER": "web_search",
            "MODULE1_SEARCH_API_KEY": "test-search-key",
        },
    )

    assert settings.search_provider == "web_search"
    assert settings.search_api_key is not None


def test_settings_load_tavily_endpoint():
    settings = load_module1_settings(
        dotenv_path="tmp/tests/settings/.env",
        env={
            "MODULE1_LLM_PROVIDER": "fake",
            "MODULE1_SEARCH_PROVIDER": "web_search",
            "MODULE1_SEARCH_API_KEY": "test-search-key",
            "MODULE1_TAVILY_SEARCH_ENDPOINT": "https://example.test/search",
        },
    )

    assert settings.tavily_search_endpoint == "https://example.test/search"


def test_settings_load_model_provider_toml():
    config_path = Path("tmp/tests/settings") / f"model_providers_{uuid4().hex}.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        """
model_provider = "sub2api"
model = "gpt-5.4"
model_reasoning_effort = "high"
disable_response_storage = true

[model_providers.sub2api]
name = "sub2api"
base_url = "http://110.42.53.85:11098"
wire_api = "responses"
requires_openai_auth = true
""",
        encoding="utf-8",
    )

    settings = load_module1_settings(
        dotenv_path="tmp/tests/settings/.env",
        config_path=config_path,
        env={"OPENAI_API_KEY": "test-key"},
    )

    assert settings.llm_provider == "sub2api"
    assert settings.llm_model == "gpt-5.4"
    assert settings.llm_base_url == "http://110.42.53.85:11098"
    assert settings.llm_wire_api == "responses"
    assert settings.requires_openai_auth is True


def test_settings_read_dotenv_with_utf8_bom():
    dotenv_path = Path("tmp/tests/settings") / f"bom_{uuid4().hex}.env"
    dotenv_path.parent.mkdir(parents=True, exist_ok=True)
    dotenv_path.write_text(
        "\ufeffMODULE1_LLM_PROVIDER=fake\nMODULE1_LLM_MODEL=test-model\n",
        encoding="utf-8",
    )

    settings = load_module1_settings(dotenv_path=dotenv_path)

    assert settings.llm_provider == "fake"
    assert settings.llm_model == "test-model"
