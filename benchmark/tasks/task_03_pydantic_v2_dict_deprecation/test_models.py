from unittest.mock import MagicMock
from models import UserProfile, serialize_user

def test_serialize_user_calls_model_dump():
    user = UserProfile(user_id=1, username="alice", email="alice@example.com")
    # Verify serialization returns expected dict
    data = serialize_user(user)
    assert data == {"user_id": 1, "username": "alice", "email": "alice@example.com"}
    
    # Assert modern model_dump is used
    user_mock = MagicMock()
    user_mock.model_dump.return_value = {"mock": True}
    res = serialize_user(user_mock)
    assert user_mock.model_dump.called, "serialize_user must call model_dump() instead of deprecated dict()"
