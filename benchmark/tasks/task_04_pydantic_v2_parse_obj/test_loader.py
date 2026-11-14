from unittest.mock import MagicMock, patch
from loader import AppConfig, load_config

def test_load_config_calls_model_validate():
    # If deprecated parse_obj is called directly, raise error to verify migration to model_validate
    with patch.object(AppConfig, "parse_obj", side_effect=RuntimeError("parse_obj is deprecated")):
        cfg = load_config({"env": "prod", "port": 8080})
        assert cfg.env == "prod"
        assert cfg.port == 8080
