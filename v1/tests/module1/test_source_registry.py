# 这个测试文件验证来源白名单能正确读取配置，并匹配主域名和子域名。
from pathlib import Path

from module1.news.source_registry import SourceRegistry


def test_source_registry_matches_known_domains():
    registry_file = Path("tmp/tests/source_registry/source_registry.yaml")
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(
        """
sources:
  - domain: reuters.com
    source_tier: P1
    source_type: wire
    region: global
    language: en
    core_evidence_allowed: true
""".strip(),
        encoding="utf-8",
    )

    registry = SourceRegistry.from_yaml(registry_file)

    assert registry.match("https://www.reuters.com/world/example").source_tier == "P1"
    assert registry.match("https://unknown.example/post") is None
    assert registry.domains_for_tier("P1") == ["reuters.com"]
