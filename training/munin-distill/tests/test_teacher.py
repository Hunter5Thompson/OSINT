from munin_distill.teacher import build_messages, generate

CTX = {"id": "x", "query": "q", "system": "SYS", "human": "HUMAN"}


def test_build_messages_uses_exact_pair():
    assert build_messages(CTX) == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "HUMAN"},
    ]


def test_generate_attaches_assistant():
    out = generate(CTX, client=lambda msgs: "GOLD REPORT")
    assert out["assistant"] == "GOLD REPORT"
    assert out["id"] == "x"
    # original context preserved
    assert out["system"] == "SYS" and out["human"] == "HUMAN"


def test_generate_passes_exact_messages_to_client():
    seen = {}

    def client(msgs):
        seen["msgs"] = msgs
        return "R"

    generate(CTX, client=client)
    assert seen["msgs"] == build_messages(CTX)
