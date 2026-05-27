# 这个测试文件验证带追踪的模块一运行器能发出中间过程事件并返回事件材料包。
from module1.settings import Module1Settings
from module1.traced_runner import run_module1_traced


def test_traced_runner_emits_steps_and_package():
    events = []
    settings = Module1Settings(
        llm_provider="fake",
        search_provider="none",
        storage_root="tmp/tests/traced_runner/data",
    )

    package, output_dir = run_module1_traced(
        "test event",
        settings=settings,
        emit=lambda step, status, message, data: events.append(
            {"step": step, "status": status, "message": message, "data": data}
        ),
    )

    steps = [event["step"] for event in events]
    assert package.event_query == "test event"
    assert output_dir.exists()
    assert "scope" in steps
    assert "timeline" in steps
    assert "storage" in steps
    assert steps[-1] == "done"
