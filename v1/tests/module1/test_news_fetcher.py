# 这个测试文件验证网页抓取器在外部网页超时或异常时不会打断整个模块一流程。
from urllib.request import Request

from module1.news.fetcher import UrlLibFetcher


def test_url_lib_fetcher_treats_timeout_as_failed_page(monkeypatch):
    def fake_urlopen(request: Request, timeout: int):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    fetcher = UrlLibFetcher(timeout=3)

    page = fetcher.fetch("https://www.reuters.com/world/example")

    assert page.status == "failed"
    assert page.error == "timed out"
