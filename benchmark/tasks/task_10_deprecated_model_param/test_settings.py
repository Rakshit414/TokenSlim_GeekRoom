import settings

def test_active_model_configured():
    # text-davinci-003 was decommissioned by OpenAI
    assert settings.DEFAULT_MODEL == "gpt-4o-mini"
