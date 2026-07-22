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
    # Zero-Token retrieval + MCP (all optional; the layer degrades to a pure-Python store without them)
    "redis>=5",
    "numpy>=1.26",
    "httpx>=0.27",
    "mcp>=1.27,<2",
    # Free-cloud provider federation (Groq + NVIDIA Build)
    "openai>=1.40",
    "python-dotenv>=1.0",
    "truststore>=0.9",
]
CITADEL_MCP_PORT = 8848


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
    from citadel import paths

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

    ws = Path(getattr(args, "workspace", None) or ".").resolve()
    redis_mode = getattr(args, "redis", None)
    redis_url = getattr(args, "redis_url", None)
    if getattr(args, "no_redis", False):
        paths.set_redis_config(ws, enabled=False)
        print("  redis         : disabled (pure-Python vector store)")
    elif redis_mode == "cloud":
        if not redis_url:
            print("  redis         : --redis cloud needs --redis-url rediss://user:pass@host:port")
        else:
            paths.set_redis_config(ws, url=redis_url)
            print(f"  redis         : cloud -> {redis_url}")
    elif redis_mode == "local" or redis_url:
        url = redis_url or "redis://127.0.0.1:6379"
        paths.set_redis_config(ws, url=url)
        print(f"  redis         : local -> {url}")
        print("     start our Redis: docker compose -f docker/compose/docker-compose.yml "
              "--profile local-redis up -d redis")
    mcp_mode = getattr(args, "mcp", None)
    if mcp_mode in ("compose", "native"):
        from citadel.commands.mcp_setup import write_mcp_json

        write_mcp_json(ws, mcp_mode, paths.resolve_redis_url(ws))
        print(f"  mcp           : {mcp_mode} config written to .mcp.json")

    print("  -> run `citadel doctor` to verify.")
    return 0


def _gpu_names() -> list[str]:
    """Every NVIDIA GPU's name via nvidia-smi (empty if none). Used for the doctor GPU + multi-GPU line."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    code, out = _run([exe, "--query-gpu=name", "--format=csv,noheader"], timeout=5)
    if code != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def probe_redis(url: str) -> tuple[bool, bool]:
    """Return (reachable, has_RediSearch). Never raises."""
    try:
        import redis

        client = redis.from_url(url, protocol=2, socket_connect_timeout=1.5)
        client.ping()
    except Exception:
        return False, False
    try:
        names: set[str] = set()
        for mod in client.execute_command("MODULE", "LIST"):
            if isinstance(mod, dict):
                names.add(mod.get(b"name") or mod.get("name"))
            elif isinstance(mod, (list, tuple)):
                for i, val in enumerate(mod):
                    if val in (b"name", "name") and i + 1 < len(mod):
                        names.add(mod[i + 1])
        decoded = {n.decode() if isinstance(n, bytes) else n for n in names if n}
        return True, "search" in decoded
    except Exception:
        return True, False


def _doctor_redis(ws, mark) -> None:
    from citadel.paths import resolve_redis_url

    url = resolve_redis_url(ws)
    if url is None:
        print("  [ok] redis: disabled (pure-Python on-disk vector store)")
        return
    reachable, has_search = probe_redis(url)
    print(f"  {mark(reachable)} redis reachable: {url}")
    if reachable:
        note = "native HNSW vectors" if has_search else "no RediSearch — on-disk fallback"
        print(f"  {mark(has_search)} RediSearch module ({note})")
    else:
        print("       (unreachable — the retrieval layer uses the pure-Python on-disk store)")


def _mcp_http_alive(port: int = 8848) -> bool:
    """A Streamable-HTTP MCP endpoint answers a bare GET with a 4xx (handshake required) = alive."""
    import urllib.error
    import urllib.request

    try:
        urllib.request.urlopen(f"http://localhost:{port}/mcp", timeout=2)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _doctor_mcp(ws, mark) -> None:
    import importlib.util
    import json

    print(f"  {mark(importlib.util.find_spec('mcp') is not None)} mcp SDK installed")
    print(f"  {mark(shutil.which('docker') is not None)} docker CLI on PATH")
    mcp_json = ws / ".mcp.json"
    servers: list[str] = []
    if mcp_json.exists():
        try:
            servers = list(json.loads(mcp_json.read_text(encoding="utf-8")).get("mcpServers", {}))
        except (OSError, ValueError):
            pass
    print(f"  {mark(bool(servers))} .mcp.json servers: {', '.join(servers) or 'none'}")
    if _mcp_http_alive():
        print("  [ok] MCP HTTP endpoint http://localhost:8848/mcp (Docker stack up)")


def _doctor_providers(mark) -> None:
    """Cloud AI providers (Groq/NVIDIA): key present? (masked, never the key itself)."""
    try:
        from citadel.services.execute.providers import PROVIDERS, resolve_provider_key
        from citadel.services.execute.providers.keys import masked
    except Exception:
        print("  [--] cloud providers: openai/python-dotenv not installed (pip install '.[providers]')")
        return
    for name, spec in PROVIDERS.items():
        key = resolve_provider_key(spec.key_env)
        n_models = len(spec.text_models) + len(spec.vision_models) + len(spec.image_models)
        print(f"  {mark(bool(key))} provider {name}: key {masked(key)} [{spec.key_env}] · {n_models} models wired")


def run_doctor(args) -> int:
    import importlib.util
    from pathlib import Path

    from citadel.paths import ensure_dot_dir, is_unsafe_placement

    def mark(ok: bool) -> str:
        return "[ok]" if ok else "[--]"

    model = getattr(args, "model", None) or OLLAMA_DEFAULT_MODEL
    print("◆ The Sovereign — doctor")
    for mod in ("anthropic", "watchdog", "yaml", "psutil", "xdist", "httpx", "redis", "numpy"):
        print(f"  {mark(importlib.util.find_spec(mod) is not None)} python: {mod}")
    print(f"  {mark(shutil.which('claude') is not None)} engine CLI on PATH")
    print(f"  {mark(ollama_exe() is not None)} ollama installed")
    print(f"  {mark(ollama_server_up())} ollama server ({OLLAMA_HOST})")
    print(f"  {mark(ollama_has_model(model))} local model: {model}")
    gpus = _gpu_names()
    if gpus:
        print(f"  [ok] GPU x{len(gpus)}: {', '.join(gpus)}")
        if len(gpus) > 1:
            print("       multi-GPU: set OLLAMA_SCHED_SPREAD=1 to spread one model across all GPUs")
    else:
        print(f"  {mark(shutil.which('nvidia-smi') is not None)} GPU (nvidia-smi)")

    ws = Path(getattr(args, "workspace", None) or ".").resolve()
    _doctor_redis(ws, mark)
    _doctor_mcp(ws, mark)
    _doctor_providers(mark)

    unsafe = is_unsafe_placement(ws / ".claude")
    print(f"  {mark(unsafe is None)} state placement (masterplan §11.2)" + ("" if unsafe is None else f": {unsafe}"))
    if getattr(args, "repair", False):
        try:
            ensure_dot_dir(ws / ".claude")
            print("  [ok] repair: .claude verified (a squatting file would be quarantined)")
        except Exception as exc:
            print(f"  [--] repair failed: {exc}")
    return 0
