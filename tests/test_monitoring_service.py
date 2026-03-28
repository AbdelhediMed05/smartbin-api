from services.monitoring_service import scrub_text, scrub_value


def test_scrub_value_redacts_password():
    data = {"username": "alice", "password": "secret123"}
    result = scrub_value(data)
    assert result["username"] == "alice"
    assert result["password"] == "[REDACTED]"


def test_scrub_value_redacts_token():
    data = {"access_token": "abc123", "name": "test"}
    result = scrub_value(data)
    assert result["access_token"] == "[REDACTED]"
    assert result["name"] == "test"


def test_scrub_value_nested():
    data = {"outer": {"secret": "hidden", "safe": "visible"}}
    result = scrub_value(data)
    assert result["outer"]["secret"] == "[REDACTED]"
    assert result["outer"]["safe"] == "visible"


def test_scrub_value_list():
    data = [{"token": "abc"}, {"name": "test"}]
    result = scrub_value(data)
    assert result[0]["token"] == "[REDACTED]"
    assert result[1]["name"] == "test"


def test_scrub_text_redacts_bearer():
    assert scrub_text("Bearer eyJhbGci...") == "[REDACTED]"


def test_scrub_text_preserves_normal():
    assert scrub_text("Hello world") == "Hello world"


def test_scrub_url_strips_sensitive_params():
    url = "https://example.com/path?user=alice&token=secret123"
    result = scrub_text(url)
    assert "alice" in result
    assert "secret123" not in result
