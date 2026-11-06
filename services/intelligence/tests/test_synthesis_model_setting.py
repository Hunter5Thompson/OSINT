from config import Settings


def test_synthesis_model_defaults_to_llm_model():
    s = Settings(vllm_model="qwen3.5", synthesis_model="")
    assert s.synthesis_llm_model == "qwen3.5"


def test_synthesis_model_override():
    s = Settings(vllm_model="qwen3.5", synthesis_model="munin")
    assert s.synthesis_llm_model == "munin"


def test_current_analysis_can_use_an_explicit_existing_inference_service(monkeypatch):
    from agents.synthesis_agent import create_synthesis_llm
    from config import settings

    monkeypatch.setattr(settings, "current_analysis_url", "http://analysis.test:8000")
    monkeypatch.setattr(settings, "current_analysis_model", "qualified-model")
    model = create_synthesis_llm(original_passages=True, current_research=True)
    assert str(model.openai_api_base) == "http://analysis.test:8000/v1"
    assert model.model_name == "qualified-model"
    assert model.max_retries == 0
