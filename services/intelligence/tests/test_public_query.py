"""Only user-authorized question text is supplied to the local query planner."""

from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage


async def test_long_german_question_becomes_a_short_public_search(monkeypatch):
    from rag.public_query import prepare_public_query

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content='{"query":"Iran attacks diplomatic negotiations latest"}'
    )
    monkeypatch.setattr("rag.public_query.ChatOpenAI", lambda **kw: model)
    question = (
        "Wie ist die aktuelle Lage im Iran und drohen neue Angriffe in den nächsten 48 Stunden?"
    )
    assert await prepare_public_query(question) == "Iran attacks diplomatic negotiations latest"
    messages = model.ainvoke.call_args.args[0]
    assert messages[-1].content == question
    assert model.ainvoke.call_args.kwargs["response_format"] == {"type": "json_object"}


async def test_invalid_planner_output_falls_back_without_executing_text(monkeypatch):
    from rag.public_query import prepare_public_query

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content='{"query":"https://localhost/secret"}')
    monkeypatch.setattr("rag.public_query.ChatOpenAI", lambda **kw: model)
    assert await prepare_public_query("Iran news") == "Iran news"
