from app.config import ROOT, load_settings


def test_dotenv_skipped(monkeypatch):
    monkeypatch.setenv("DIACRITIZER_SKIP_DOTENV", "1")
    monkeypatch.setattr("app.config.dotenv_values", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("read .env")))
    monkeypatch.setenv("SERVICE_KEY", "isolated")
    assert load_settings().service_key == ""


def test_dotenv_exact_path(monkeypatch):
    calls = []
    monkeypatch.setenv("DIACRITIZER_SKIP_DOTENV", "0")
    def fake_values(*a, **kw):
        calls.append((a, kw))
        return {"SERVICE_KEY": "file-only"}
    monkeypatch.setattr("app.config.dotenv_values", fake_values)
    monkeypatch.setenv("SERVICE_KEY", "inherited-key-must-not-win")
    assert load_settings().service_key == "file-only"
    assert calls == [((ROOT / ".env",), {"interpolate": False})]
