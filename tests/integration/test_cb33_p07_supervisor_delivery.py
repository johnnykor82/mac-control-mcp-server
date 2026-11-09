"""CB33 P07R: the whole original answer must go in one Supervisor request."""
import hashlib

import pytest
from mac_control.watcher_runtime import watcher_goal_supervisor as goals


@pytest.mark.parametrize("length", [18454, 130000, 1000000])
def test_supervisor_contains_all_unmodified_characters(length):
    marker="CB33_P07R_FINAL_MARKER"
    answer="Ж"*(length-len(marker))+marker
    source_sha=hashlib.sha256(answer.encode("utf-8")).hexdigest()
    row={"criteria":"Verify exact final marker", "max_turns":1}
    turn={"assistant_message_id":"original-source-id", "turn_index":1,
          "answer":answer,"answer_sha256":source_sha}
    prompt=goals._review_prompt(row,turn)
    assert answer in prompt
    assert marker in prompt
    assert source_sha in prompt
    assert prompt.count(answer)==1
    assert prompt.count(marker)==1


def test_supervisor_rejects_changed_durable_source_hash():
    turn={"assistant_message_id":"source-1","turn_index":1,
          "answer":"original text","answer_sha256":"0"*64}
    with pytest.raises(ValueError,match="SHA256"):
        goals._review_prompt({"criteria":"Check","max_turns":1},turn)


def test_supervisor_decision_retains_long_control_text():
    import json
    marker="P07R_FINAL"
    rationale="Ф"*20000+marker
    instruction="П"*150000+marker
    payload=json.dumps({"action":"continue","source_turn_id":"original-source-id",
                        "criteria_assessment":[],"rationale":rationale,
                        "next_instruction":instruction},ensure_ascii=False)
    decision=goals._parse_decision(payload,{"assistant_message_id":"original-source-id"})
    assert decision["rationale"]==rationale
    assert decision["next_instruction"]==instruction


def test_notification_batch_keeps_full_large_payload():
    from mac_control.watcher_runtime import watcher_busy_batch
    suffix="CB33_P07R_NOTIFICATION_END"
    content="Н"*130000+suffix
    rows=[{"payload":content},{"payload":"second result"}]
    selected=watcher_busy_batch.choose(rows)
    assert len(selected)==2
    assert selected[0]["payload"]==content
    assert selected[0]["payload"].endswith(suffix)
