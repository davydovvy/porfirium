import json
from pathlib import Path

from portal_api.publisher import candidate_from_directory, offline_report

CANARY = Path(__file__).parents[3] / "agents/tool-assistant/1.3.0"


def test_canary_offline_report_is_bounded_and_stable() -> None:
    candidate = candidate_from_directory(CANARY)
    report = offline_report(candidate)
    assert report["agent_id"] == "tool-assistant"
    assert report["version"] == "1.3.0"
    assert report["digest"].startswith("sha256:")
    assert report["artifact_size"] == len(candidate.artifact)
    assert json.loads(candidate.artifact)["tools"] == [
        "demo_time-get_current_time",
        "demo_time-convert_time",
    ]
