from pydantic import BaseModel

class AppConfig(BaseModel):
    env: str
    port: int

def load_config(raw_dict: dict) -> AppConfig:
    # Stale/deprecated in Pydantic v2
    return AppConfig.parse_obj(raw_dict)
