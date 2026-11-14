from pydantic import BaseModel

class UserProfile(BaseModel):
    user_id: int
    username: str
    email: str

def serialize_user(user: UserProfile) -> dict:
    # Stale/deprecated API usage in Pydantic v2
    return user.dict()
