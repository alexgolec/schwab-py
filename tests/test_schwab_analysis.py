import json
import sys
import importlib.util
from pathlib import Path
import pytest


def load_module():
    # Dynamically import the schwab-analysis script from the bin directory
    module_path = Path(__file__).parents[1] / "bin" / "schwab-analysis.py"
    spec = importlib.util.spec_from_file_location("schwab-analysis", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ta():
    return load_module()


def test_split_seconds_positive(ta):
    days, hours, minutes, seconds = ta.TimeUtils.split_seconds(90061)
    assert (days, hours, minutes, seconds) == (1, 1, 1, 1)


def test_split_seconds_negative(ta):
    days, hours, minutes, seconds = ta.TimeUtils.split_seconds(-90061)
    assert (days, hours, minutes, seconds) == (1, 1, 1, 1)


def test_format_timestamp(ta):
    # 2021-01-01 00:00:00 UTC
    ts = 1609459200
    assert ta.TimeUtils.format_timestamp(ts) == "2021-01-01 00:00:00 UTC"


def test_load_token_data_file_not_found(ta, tmp_path):
    with pytest.raises(FileNotFoundError):
        ta.TokenAnalyzer().load_token_data(tmp_path / "no_such_file.json")


def test_load_token_data_invalid_json(ta, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ invalid json }")
    with pytest.raises(ValueError) as exc:
        ta.TokenAnalyzer().load_token_data(p)
    assert "Invalid JSON" in str(exc.value)


def test_load_token_data_missing_fields(ta, tmp_path):
    p = tmp_path / "missing.json"
    p.write_text(json.dumps({"token": {}}))  # missing creation_timestamp
    with pytest.raises(ValueError) as exc:
        ta.TokenAnalyzer().load_token_data(p)
    assert "Missing required fields" in str(exc.value)


def test_load_token_data_success(ta, tmp_path):
    data = {
        "token": {
            "refresh_token": "r",
            "access_token": "a",
            "token_type": "t",
            "expires_in": 100,
            "expires_at": 200,
            "scope": "s"
        },
        "creation_timestamp": 50
    }
    p = tmp_path / "token.json"
    p.write_text(json.dumps(data))
    out = ta.TokenAnalyzer().load_token_data(p)
    assert out["creation_timestamp"] == 50
    assert out["token"]["access_token"] == "a"


def test_analyze_token(ta, monkeypatch):
    # Freeze current time
    monkeypatch.setattr(ta.time, "time", lambda: 150)
    data = {
        "token": {
            "refresh_token": "r",
            "access_token": "a",
            "token_type": "t",
            "expires_in": 100,
            "expires_at": 200,
            "scope": "s"
        },
        "creation_timestamp": 50
    }
    analyzer = ta.TokenAnalyzer(refresh_threshold_seconds=60)
    result = analyzer.analyze_token(data)
    assert result.age_seconds == 100  # 150 - 50
    assert result.time_until_expiry == 50  # 200 - 150
    assert not result.is_expired
    assert result.should_refresh


def test_get_installed_version(ta, monkeypatch):
    # Simulate installed package
    monkeypatch.setattr(ta.metadata, "version", lambda name: "1.0.0")
    assert ta.PackageVersionChecker.get_installed_version("foo") == "1.0.0"
    # Simulate not installed
    def _raise(name): raise ta.metadata.PackageNotFoundError
    monkeypatch.setattr(ta.metadata, "version", _raise)
    assert ta.PackageVersionChecker.get_installed_version("foo") == "not installed"


def test_get_latest_version_success(ta, monkeypatch):
    class DummyResponse:
        def raise_for_status(self): pass
        def json(self): return {"info": {"version": "2.0.0"}}

    class DummyClient:
        def __init__(self, timeout): pass
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): pass
        def get(self, url): return DummyResponse()

    monkeypatch.setattr(ta.httpx, "Client", DummyClient)
    pvc = ta.PackageVersionChecker()
    assert pvc.get_latest_version("pkg") == "2.0.0"


def test_get_latest_version_error(ta, monkeypatch):
    class DummyClient:
        def __init__(self, timeout): pass
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): pass
        def get(self, url): raise ta.httpx.HTTPError("error fetching")

    monkeypatch.setattr(ta.httpx, "Client", DummyClient)
    pvc = ta.PackageVersionChecker()
    assert pvc.get_latest_version("pkg") is None


def test_check_package_info(ta, monkeypatch):
    pvc = ta.PackageVersionChecker()
    monkeypatch.setattr(pvc, "get_installed_version", lambda name: "1.0.0")
    monkeypatch.setattr(pvc, "get_latest_version", lambda name: "1.1.0")
    info = pvc.check_package_info("pkg", check_updates=True)
    assert info.installed_version == "1.0.0"
    assert info.latest_version == "1.1.0"
    assert info.update_available
    assert info.is_installed


def test_get_all_versions(ta, monkeypatch):
    monkeypatch.setattr(
        ta.PackageVersionChecker,
        "get_installed_version",
        lambda name: "1.2.3"
    )
    versions = ta.PackageVersionChecker.get_all_versions()
    assert isinstance(versions, dict)
    for version in versions.values():
        assert version == "1.2.3"


def test_parse_arguments_defaults(ta, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog"])
    args = ta.parse_arguments()
    assert not args.check_updates
    assert args.token_path == Path("token.json")
    assert args.timeout == 10
    assert args.refresh_threshold == 300


def test_parse_arguments_custom(ta, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["prog", "-u", "-t", "file.json", "--timeout", "5", "--refresh-threshold", "7"])
    args = ta.parse_arguments()
    assert args.check_updates
    assert args.token_path == Path("file.json")
    assert args.timeout == 5
    assert args.refresh_threshold == 7


def test_schwab_api_tester_create_client(ta, monkeypatch, tmp_path):
    sentinel = object()
    monkeypatch.setattr(ta, "client_from_token_file", lambda api_key, app_secret, token_path: sentinel)
    tester = ta.SchwabAPITester("key", "secret")
    client = tester.create_client(tmp_path / "dummy.json")
    assert client is sentinel


def test_test_quote_retrieval(ta, monkeypatch):
    class DummyResponse:
        def raise_for_status(self): pass
        def json(self): return {"SYM": {"regular": {"regularMarketLastPrice": 123.45}}}

    client = type("C", (), {"get_quote": lambda self, sym: DummyResponse()})()
    # Freeze perf_counter
    times = iter([1.0, 2.5])
    monkeypatch.setattr(ta.time, "perf_counter", lambda: next(times))
    elapsed, data = ta.SchwabAPITester("k", "s").test_quote_retrieval(client, symbol="SYM")
    assert elapsed == pytest.approx(1.5)
    assert data == {"SYM": {"regular": {"regularMarketLastPrice": 123.45}}}
