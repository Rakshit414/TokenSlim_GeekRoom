from datetime import datetime, timezone

class SessionManager:
    @staticmethod
    def create_session(user_id: str) -> dict:
        # Deprecated naive datetime in Python 3.12+
        created_at = datetime.utcnow()
        return {
            "user_id": user_id,
            "created_at": created_at
        }
