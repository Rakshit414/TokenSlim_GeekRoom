from session import SessionManager

def test_session_has_timezone_aware_timestamp():
    session = SessionManager.create_session("usr_123")
    dt = session["created_at"]
    # Deprecated utcnow() produces naive datetimes where tzinfo is None
    assert dt.tzinfo is not None, "Timestamp must be timezone-aware (tzinfo is not None)"
