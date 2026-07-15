"""citadel setup / doctor — auto-install everything The Sovereign needs, and report readiness.

`setup` pip-installs the Python extras, installs Ollama and pulls a default local model, and (opt-in)
best-effort installs the heavy ML libraries. `doctor` reports what is installed / missing / how to fix,
including the GPU and the underlying CLI. So the user only installs citadel; setup does the rest.
"""

import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

OLLAMA_DEFAULT_MODEL = "qwen2.5-coder:7b"
OLLAMA_HOST = "http://localhost:11434"
PIP_EXTRAS = [
    "anthropic>=0.116.0",
    "watchdog>=6.0.0",
    "PyYAML>=6.0.3",
    "psutil>=5.9",
    "matplotlib>=3.11.0",
    "pytest-xdist>=3.8.0",
]


def _run(cmd: list[str], timeout: float | None = None) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def ollama_exe() -> str | None:
    exe = shutil.which("ollama")
    if exe:
        return exe
    candidate = Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
    return str(candidate) if candidate.exists() else None


def ollama_server_up(host: str = OLLAMA_HOST) -> bool:
    try:
        urllib.request.urlopen(f"{host}/api/tags", timeout=2)
        return True
    except Exception:
        return False


def ollama_has_model(model: str, host: str = OLLAMA_HOST) -> bool:
    try:
        import json
        with urllib.request.urlopen(f"{host}/api/tags", timeout=2) as resp:
            tags = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False
    return any(model in (m.get("name") or "") for m in tags.get("models", []))


def install_ollama() -> str:
    if ollama_exe():
        return "already installed"
    system = platform.system()
    if system == "Windows":
        if shutil.which("winget"):
            code, out = _run(
                ["winget", "install", "--id", "Ollama.Ollama", "-e", "--source", "winget",
                 "--silent", "--accept-package-agreements", "--accept-source-agreements"],
                timeout=900,
            )
            return "installed" if code == 0 else f"winget failed: {out[-160:]}"
        return "winget unavailable — install from https://ollama.com/download"
    if system in ("Linux", "Darwin"):
        code, out = _run(["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"], timeout=900)
        return "installed" if code == 0 else f"install script failed: {out[-160:]}"
    return f"unsupported platform {system} — install from https://ollama.com/download"


def pull_model(model: str = OLLAMA_DEFAULT_MODEL) -> str:
    exe = ollama_exe()
    if not exe:
        return "ollama not installed"
    if ollama_has_model(model):
        return "already present"
    code, out = _run([exe, "pull", model], timeout=900)
    return "pulled" if code == 0 else f"pull failed: {out[-160:]}"


def pip_install(pkgs: list[str]) -> tuple[bool, str]:
    code, out = _run([sys.executable, "-m", "pip", "install", "--upgrade", *pkgs], timeout=1200)
    return code == 0, out


def run_setup(args) -> int:
    print("◆ The Sovereign — setup")
    ok, out = pip_install(PIP_EXTRAS)
    print(f"  python extras : {'ok' if ok else 'FAILED'}")
    if not ok:
        print("   " + out[-300:])
    print(f"  ollama        : {install_ollama()}")
    model = getattr(args, "model", None) or OLLAMA_DEFAULT_MODEL
    print(f"  model {model}: {pull_model(model)}")
    if getattr(args, "with_ml", False):
        ok_ml, _ = pip_install(["llama-cpp-python"])
        print(f"  llama-cpp     : {'ok' if ok_ml else 'skipped/failed (needs a compiler or prebuilt wheel)'}")
    print("  -> run `citadel doctor` to verify.")
    return 0


def run_doctor(args) -> int:
    import importlib.util
    from pathlib import Path

    from citadel.paths import ensure_dot_dir, is_unsafe_placement

    def mark(ok: bool) -> str:
        return "[ok]" if ok else "[--]"

    model = getattr(args, "model", None) or OLLAMA_DEFAULT_MODEL
    print("◆ The Sovereign — doctor")
    for mod in ("anthropic", "watchdog", "yaml", "psutil", "xdist"):
        print(f"  {mark(importlib.util.find_spec(mod) is not None)} python: {mod}")
    print(f"  {mark(shutil.which('claude') is not None)} engine CLI on PATH")
    print(f"  {mark(ollama_exe() is not None)} ollama installed")
    print(f"  {mark(ollama_server_up())} ollama server ({OLLAMA_HOST})")
    print(f"  {mark(ollama_has_model(model))} local model: {model}")
    print(f"  {mark(shutil.which('nvidia-smi') is not None)} GPU (nvidia-smi)")

    ws = Path(getattr(args, "workspace", None) or ".").resolve()
    unsafe = is_unsafe_placement(ws / ".claude")
    print(f"  {mark(unsafe is None)} state placement (masterplan §11.2)" + ("" if unsafe is None else f": {unsafe}"))
    if getattr(args, "repair", False):
        try:
            ensure_dot_dir(ws / ".claude")
            print("  [ok] repair: .claude verified (a squatting file would be quarantined)")
        except Exception as exc:
            print(f"  [--] repair failed: {exc}")
    return 0
