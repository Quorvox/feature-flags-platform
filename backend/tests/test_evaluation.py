"""Unit tests for pure evaluation logic. No DB/Redis needed."""
from app.main import default_off, in_rollout, resolve_flag


def test_killswitch_off():
    p = {"key": "x", "type": "boolean", "enabled": False, "value": True, "rollout_percentage": 100}
    r = resolve_flag(p, {"user_id": "u1"})
    assert r.enabled is False and r.reason == "off_killswitch" and r.value is False


def test_rollout_100_always_on():
    p = {"key": "x", "type": "boolean", "enabled": True, "value": True, "rollout_percentage": 100}
    assert resolve_flag(p, {"user_id": "any"}).reason == "on"


def test_rollout_0_always_off():
    p = {"key": "x", "type": "boolean", "enabled": True, "value": True, "rollout_percentage": 0}
    r = resolve_flag(p, {"user_id": "any"})
    assert r.enabled is False and r.reason == "off_rollout"


def test_rollout_deterministic():
    p = {"key": "flag1", "type": "boolean", "enabled": True, "value": True, "rollout_percentage": 50}
    a = resolve_flag(p, {"user_id": "user_123"})
    b = resolve_flag(p, {"user_id": "user_123"})
    assert a.enabled == b.enabled and a.reason == b.reason


def test_in_rollout_bounds():
    assert in_rollout("k", "u", 100) is True
    assert in_rollout("k", "u", 0) is False
    assert isinstance(in_rollout("k", "u", 50), bool)


def test_default_off_types():
    assert default_off({"type": "boolean"}) is False
    assert default_off({"type": "number"}) == 0
    assert default_off({"type": "string"}) == ""
    assert default_off({"type": "json"}) is None


def test_string_flag_value_passthrough():
    p = {"key": "pay", "type": "string", "enabled": True, "value": "https://pay.example.com/v2",
         "rollout_percentage": 100}
    r = resolve_flag(p, {"user_id": "u"})
    assert r.enabled is True and r.value == "https://pay.example.com/v2"
