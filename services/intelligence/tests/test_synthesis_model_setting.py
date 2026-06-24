from config import Settings


def test_synthesis_model_defaults_to_llm_model():
    s = Settings(vllm_model="qwen3.5", synthesis_model="")
    assert s.synthesis_llm_model == "qwen3.5"


def test_synthesis_model_override():
    s = Settings(vllm_model="qwen3.5", synthesis_model="munin")
    assert s.synthesis_llm_model == "munin"
