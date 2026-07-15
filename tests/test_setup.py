"""citadel setup/doctor: detection helpers and that doctor runs without side effects."""

from citadel.commands import setup


def test_ollama_exe_returns_str_or_none():
    result = setup.ollama_exe()
    assert result is None or isinstance(result, str)


def test_ollama_server_up_false_on_unreachable():
    assert setup.ollama_server_up("http://localhost:1") is False


def test_ollama_has_model_false_on_bad_host():
    assert setup.ollama_has_model("qwen2.5:0.5b", host="http://localhost:1") is False


def test_pip_extras_include_key_packages():
    joined = " ".join(setup.PIP_EXTRAS)
    assert "watchdog" in joined
    assert "pytest-xdist" in joined
    assert "psutil" in joined


def test_run_doctor_runs_clean(capsys):
    class Args:
        model = None

    assert setup.run_doctor(Args()) == 0
    out = capsys.readouterr().out
    assert "The Sovereign" in out
    assert "ollama" in out
