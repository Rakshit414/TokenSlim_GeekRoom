from unittest.mock import MagicMock, patch
import llm_gateway

def test_query_model_uses_instantiated_client():
    with patch("openai.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content="Mock response"))
        ]
        res = llm_gateway.query_model("Hello")
        assert res == "Mock response"
        assert mock_client.chat.completions.create.called
