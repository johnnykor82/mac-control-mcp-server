from mac_control.watcher_runtime import watcher_autonomous as autonomous
from mac_control.watcher_runtime import watcher_browser_dispatch as dispatch


def test_autonomous_accepts_large_one_piece_executor_prompt():
    content="Ж"*130000+"CB33_P07R_END"
    digest=autonomous._validate("cb33-test","new-task",
        "WC"+"a"*16,content,"cb33-p07r-idem-key","123")
    assert len(digest)==64


def test_browser_dispatch_accepts_large_one_piece_prompt():
    content="Ж"*130000+"CB33_P07R_END"
    parsed=dispatch._check_input("cb33-test","new-task",
        "https://chatgpt.com/c/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        content,"cb33-p07r-idem-key","123")
    assert parsed[1]
