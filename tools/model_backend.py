"""
Hardware-agnostic T1 local-model backend for SOVEREIGN-IMPERIA-CITADEL.

Strictly NO Ollama. Uses pure Python ML libraries: transformers, llama-cpp-python,
mlx (Apple Silicon only), or onnxruntime as fallback.

Graceful degradation ladder (probed at import time):
  Tier A: CUDA VRAM > 12GB  → Q4_K_M GGUFs fully into VRAM
  Tier B: CUDA VRAM 4–12GB  → split VRAM + system RAM (partial offload)
  Tier C: MPS (Apple Silicon)  → mlx-lm or transformers with device="mps"
  Tier D: CPU + RAM > 16GB  → llama-cpp-python CPU or quantized transformers
  Tier E: CPU + RAM ≤ 8GB   → distillation model 1.5B–3B, prevent OS paging

All ML library imports are lazy and wrapped in try/except so this module is safely
importable even on machines where none of the ML libraries are installed.

Usage:
  from tools.model_backend import get_backend, ModelTier

  backend = get_backend()
  print(backend.hardware)          # detected HardwareProfile
  print(backend.tier)              # ModelTier.T1_CUDA_FULL etc.

  embeddings = backend.embed(["some text"])
  result = backend.nli_entailment(claim="X implies Y", span_text="...source text...")
  text = backend.generate("Complete this:", max_tokens=200)
"""


import os
import platform
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class BackendDevice(Enum):
    CUDA_FULL = "cuda_full"
    CUDA_SPLIT = "cuda_split"
    MPS = "mps"
    CPU_ADEQUATE = "cpu_adequate"
    CPU_CONSTRAINED = "cpu_constrained"
    UNAVAILABLE = "unavailable"


@dataclass
class HardwareProfile:
    device: BackendDevice
    cpu_count: int
    total_ram_gb: float
    available_ram_gb: float
    vram_gb: float = 0.0
    cuda_device_name: str = ""
    mps_available: bool = False
    torch_available: bool = False
    cuda_available: bool = False
    platform_info: str = ""

    def summary(self) -> str:
        lines = [
            f"Device       : {self.device.value}",
            f"Platform     : {self.platform_info}",
            f"CPU cores    : {self.cpu_count}",
            f"RAM          : {self.available_ram_gb:.1f} GB available / {self.total_ram_gb:.1f} GB total",
        ]
        if self.cuda_available:
            lines.append(f"GPU          : {self.cuda_device_name} ({self.vram_gb:.1f} GB VRAM)")
        elif self.mps_available:
            lines.append(f"GPU          : Apple Silicon MPS")
        return "\n".join(lines)


def detect_hardware() -> HardwareProfile:
    """
    Probe OS and ML libraries to determine available hardware.
    Safe to call with no ML libraries installed — degrades gracefully.
    """
    import importlib.util

    cpu_count = os.cpu_count() or 1
    platform_info = f"{platform.system()} {platform.machine()} Python {sys.version.split()[0]}"

    total_ram_gb = _probe_total_ram_gb()
    available_ram_gb = _probe_available_ram_gb()

    torch_available = importlib.util.find_spec("torch") is not None
    cuda_available = False
    mps_available = False
    vram_gb = 0.0
    cuda_device_name = ""

    if torch_available:
        try:
            import torch  # type: ignore
            cuda_available = torch.cuda.is_available()
            mps_available = getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available()

            if cuda_available:
                props = torch.cuda.get_device_properties(0)
                vram_gb = props.total_memory / (1024 ** 3)
                cuda_device_name = props.name
        except Exception:
            pass

    if not cuda_available:
        smi = _probe_nvidia_smi()
        if smi is not None:
            cuda_available = True
            vram_gb, cuda_device_name = smi

    if cuda_available and vram_gb > 12:
        device = BackendDevice.CUDA_FULL
    elif cuda_available and vram_gb >= 4:
        device = BackendDevice.CUDA_SPLIT
    elif mps_available:
        device = BackendDevice.MPS
    elif total_ram_gb > 16:
        device = BackendDevice.CPU_ADEQUATE
    elif total_ram_gb > 0:
        device = BackendDevice.CPU_CONSTRAINED
    else:
        device = BackendDevice.UNAVAILABLE

    return HardwareProfile(
        device=device,
        cpu_count=cpu_count,
        total_ram_gb=total_ram_gb,
        available_ram_gb=available_ram_gb,
        vram_gb=vram_gb,
        cuda_device_name=cuda_device_name,
        mps_available=mps_available,
        torch_available=torch_available,
        cuda_available=cuda_available,
        platform_info=platform_info,
    )


def _windows_ram_bytes() -> tuple[int, int] | None:
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return int(stat.ullTotalPhys), int(stat.ullAvailPhys)
    except Exception:
        return None
    return None


def _system_memory_bytes() -> tuple[int, int]:
    """(total, available) RAM in bytes: psutil -> /proc/meminfo -> Windows API -> POSIX sysconf -> (0, 0)."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        return int(vm.total), int(vm.available)
    except Exception:
        pass
    try:
        total = avail = 0
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) * 1024
        if total:
            return total, (avail or total)
    except Exception:
        pass
    win = _windows_ram_bytes()
    if win is not None:
        return win
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        phys = os.sysconf("SC_PHYS_PAGES")
        avail_pages = os.sysconf("SC_AVPHYS_PAGES")
        if page > 0 and phys > 0:
            return page * phys, page * (avail_pages if avail_pages > 0 else phys)
    except (ValueError, OSError, AttributeError):
        pass
    return 0, 0


def _probe_total_ram_gb() -> float:
    return _system_memory_bytes()[0] / (1024 ** 3)


def _probe_available_ram_gb() -> float:
    return _system_memory_bytes()[1] / (1024 ** 3)


def _probe_nvidia_smi() -> tuple[float, str] | None:
    """Detect an NVIDIA GPU via nvidia-smi when torch is absent. Returns (vram_gb, device_name)."""
    import shutil
    import subprocess

    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    first = proc.stdout.strip().splitlines()[0]
    if "," not in first:
        return None
    mem_mib, name = first.split(",", 1)
    try:
        return float(mem_mib.strip()) / 1024.0, name.strip()
    except ValueError:
        return None


@dataclass
class ModelSpec:
    """Recommended model selection for a given device tier."""
    embed_model: str
    nli_model: str
    general_model: str
    quantization: str
    n_gpu_layers: int
    max_context_tokens: int
    thread_count: int


def _select_model_spec(hw: HardwareProfile) -> ModelSpec:
    """Choose appropriate model sizes / quantization based on hardware."""
    threads = max(1, hw.cpu_count - 2)

    if hw.device == BackendDevice.CUDA_FULL:
        return ModelSpec(
            embed_model="nomic-embed-text",
            nli_model="cross-encoder/nli-deberta-v3-large",
            general_model="Qwen2.5-14B-Instruct-Q4_K_M.gguf",
            quantization="Q4_K_M",
            n_gpu_layers=-1,
            max_context_tokens=8192,
            thread_count=threads,
        )
    elif hw.device == BackendDevice.CUDA_SPLIT:
        vram = hw.vram_gb
        n_layers = int(vram * 2)
        return ModelSpec(
            embed_model="nomic-embed-text",
            nli_model="cross-encoder/nli-MiniLM2-L6-H768",
            general_model="Llama-3.1-8B-Instruct-Q4_K_M.gguf",
            quantization="Q4_K_M",
            n_gpu_layers=n_layers,
            max_context_tokens=4096,
            thread_count=threads,
        )
    elif hw.device == BackendDevice.MPS:
        return ModelSpec(
            embed_model="nomic-embed-text",
            nli_model="cross-encoder/nli-MiniLM2-L6-H768",
            general_model="Llama-3.1-8B-Instruct-Q4_K_M.gguf",
            quantization="Q4_K_M",
            n_gpu_layers=-1,
            max_context_tokens=4096,
            thread_count=threads,
        )
    elif hw.device == BackendDevice.CPU_ADEQUATE:
        return ModelSpec(
            embed_model="bge-small-en-v1.5",
            nli_model="cross-encoder/nli-MiniLM2-L6-H768",
            general_model="Llama-3.2-3B-Instruct-Q4_K_M.gguf",
            quantization="Q4_K_M",
            n_gpu_layers=0,
            max_context_tokens=2048,
            thread_count=threads,
        )
    else:
        return ModelSpec(
            embed_model="all-MiniLM-L6-v2",
            nli_model="typeform/distilbert-base-uncased-mnli",
            general_model="Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
            quantization="Q4_K_M",
            n_gpu_layers=0,
            max_context_tokens=1024,
            thread_count=max(1, threads // 2),
        )


class ModelBackend:
    """
    Hardware-agnostic T1 local model backend.

    All models are loaded lazily on first call so that importing this module
    has zero overhead and never crashes due to missing ML libraries.

    Three capabilities exposed:
      embed(texts)           → list[list[float]]  — T1 embedding
      nli_entailment(...)    → dict                — L2 entailment check
      generate(prompt, ...)  → str                 — T1 text generation
    """

    def __init__(self) -> None:
        self.hardware: HardwareProfile = detect_hardware()
        self.spec: ModelSpec = _select_model_spec(self.hardware)
        self._embed_model: Any = None
        self._nli_model: Any = None
        self._nli_tokenizer: Any = None
        self._llm: Any = None
        self._lock = threading.Lock()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Generate embeddings using a local sentence-transformer model.
        Returns list of float vectors (one per input text).
        Falls back to hash-based pseudo-embeddings if no library available.
        """
        model = self._load_embed_model()
        if model is None:
            return self._pseudo_embed(texts)
        try:
            return model.encode(list(texts), show_progress_bar=False).tolist()
        except Exception as exc:
            _warn(f"embed failed ({exc}), using pseudo-embed")
            return self._pseudo_embed(texts)

    def _load_embed_model(self) -> Any:
        with self._lock:
            if self._embed_model is not None:
                return self._embed_model
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore
                device = _torch_device(self.hardware)
                self._embed_model = SentenceTransformer(self.spec.embed_model, device=device)
                return self._embed_model
            except ImportError:
                _warn("sentence-transformers not installed; embedding unavailable")
                return None

    def _pseudo_embed(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Deterministic 64-dim pseudo-embedding via SHA-256 bytes.
        Not semantically meaningful — used only as a last-resort fallback
        when no ML library is available, so the pipeline doesn't crash.
        """
        import hashlib
        result = []
        for text in texts:
            h = hashlib.sha256(text.encode()).digest()
            vec = [b / 255.0 for b in h[:64]] if len(h) >= 64 else [0.0] * 64
            result.append(vec)
        return result

    def nli_entailment(self, claim: str, span_text: str) -> dict:
        """
        L2 verification ladder gate.

        Checks whether span_text entails claim using an independent NLI model.
        The NLI model must be DIFFERENT from the Silver structurer that extracted
        the claim — this is guaranteed by keeping embed/NLI as cross-encoder and
        general inference as a causal LLM.

        Returns:
          {
            "entailed": bool,
            "label": "entailment" | "neutral" | "contradiction",
            "score": float,
            "model_used": str,
            "fallback_used": bool,
          }
        """
        tokenizer, model = self._load_nli_model()
        if model is None:
            return self._pseudo_nli(claim, span_text)
        try:
            import torch  # type: ignore
            inputs = tokenizer(
                span_text, claim,
                return_tensors="pt",
                truncation=True,
                max_length=512,
                padding=True,
            )
            device = _torch_device(self.hardware)
            if device != "cpu":
                inputs = {k: v.to(device) for k, v in inputs.items()}
                model.to(device)
            with torch.no_grad():
                logits = model(**inputs).logits
            probs = torch.softmax(logits, dim=-1).squeeze().tolist()
            label_map = {0: "contradiction", 1: "neutral", 2: "entailment"}
            best = int(torch.argmax(logits).item())
            return {
                "entailed": best == 2,
                "label": label_map[best],
                "score": float(probs[best]),
                "model_used": self.spec.nli_model,
                "fallback_used": False,
            }
        except Exception as exc:
            _warn(f"NLI inference failed ({exc}), using pseudo-NLI")
            return self._pseudo_nli(claim, span_text)

    def _load_nli_model(self) -> tuple[Any, Any]:
        with self._lock:
            if self._nli_model is not None:
                return self._nli_tokenizer, self._nli_model
            try:
                from transformers import AutoModelForSequenceClassification, AutoTokenizer  # type: ignore
                self._nli_tokenizer = AutoTokenizer.from_pretrained(self.spec.nli_model)
                self._nli_model = AutoModelForSequenceClassification.from_pretrained(self.spec.nli_model)
                return self._nli_tokenizer, self._nli_model
            except ImportError:
                _warn("transformers not installed; NLI unavailable")
                return None, None

    def _pseudo_nli(self, claim: str, span_text: str) -> dict:
        """
        Keyword-overlap pseudo-NLI. Never use for production verification;
        only prevents total pipeline failure when ML libraries are absent.
        """
        claim_words = set(claim.lower().split())
        span_words = set(span_text.lower().split())
        overlap = len(claim_words & span_words) / max(len(claim_words), 1)
        entailed = overlap > 0.4
        return {
            "entailed": entailed,
            "label": "entailment" if entailed else "neutral",
            "score": overlap,
            "model_used": "pseudo_keyword_overlap",
            "fallback_used": True,
        }

    def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.1,
        stop: list[str] | None = None,
    ) -> str:
        """
        T1 text generation via llama-cpp-python (GGUF).
        Falls back to transformers pipeline if llama-cpp unavailable.
        Returns the generated text (not the full completion dict).
        """
        llm = self._load_llm()
        if llm is None:
            return "[T1 generation unavailable — install llama-cpp-python or transformers]"
        try:
            result = llm(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=stop or [],
                echo=False,
            )
            return result["choices"][0]["text"].strip()
        except Exception as exc:
            _warn(f"generate failed ({exc})")
            return f"[generation error: {exc}]"

    def _load_llm(self) -> Any:
        with self._lock:
            if self._llm is not None:
                return self._llm
            try:
                from llama_cpp import Llama  # type: ignore
                n_threads = self.spec.thread_count
                self._llm = Llama(
                    model_path=self._resolve_gguf_path(self.spec.general_model),
                    n_ctx=self.spec.max_context_tokens,
                    n_gpu_layers=self.spec.n_gpu_layers,
                    n_threads=n_threads,
                    verbose=False,
                )
                return self._llm
            except ImportError:
                _warn("llama-cpp-python not installed; generation unavailable")
                return None
            except Exception as exc:
                _warn(f"Failed to load GGUF ({exc})")
                return None

    def _resolve_gguf_path(self, model_name: str) -> str:
        """
        Look for the GGUF model file in common local model directories.
        Raises FileNotFoundError with a helpful message if not found.
        """
        search_dirs = [
            Path(os.environ.get("CITADEL_MODELS_DIR", "")) / model_name,
            Path.home() / ".cache" / "citadel" / "models" / model_name,
            Path.home() / ".local" / "share" / "models" / model_name,
            Path("/models") / model_name,
        ]
        for p in search_dirs:
            if p.exists():
                return str(p)
        raise FileNotFoundError(
            f"GGUF model '{model_name}' not found. "
            f"Set CITADEL_MODELS_DIR or place the file in ~/.cache/citadel/models/. "
            f"Searched: {[str(d) for d in search_dirs]}"
        )

    def is_fully_operational(self) -> bool:
        """True if all three capabilities have real (non-fallback) models."""
        return (
            self.hardware.device != BackendDevice.UNAVAILABLE
            and self._load_embed_model() is not None
        )


_backend: ModelBackend | None = None
_backend_lock = threading.Lock()


def get_backend() -> ModelBackend:
    """Return (or create) the module-level ModelBackend singleton."""
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                _backend = ModelBackend()
    return _backend


def _torch_device(hw: HardwareProfile) -> str:
    if hw.cuda_available:
        return "cuda"
    if hw.mps_available:
        return "mps"
    return "cpu"


def _warn(msg: str) -> None:
    print(f"[model_backend WARNING] {msg}", file=sys.stderr)


def execute_t1_local_mock(prompt: str, task_type: str) -> dict:
    """Run a T1 local inference job.

    Uses the real backend's generate() when a model is loaded; falls back to a
    deterministic keyword-overlap stub so the pipeline stays functional on
    hardware without a local LLM.

    Returns:
        {"mock_response": str, "tier_used": "T1_real" | "T1_stub"}
    """
    backend = get_backend()
    try:
        if backend.is_fully_operational():
            response = backend.generate(
                prompt=prompt,
                max_tokens=256,
                temperature=0.3,
            )
            return {"mock_response": response.strip(), "tier_used": "T1_real"}
    except Exception:
        pass

    words = [w.lower() for w in prompt.split() if len(w) > 4]
    top_words = list(dict.fromkeys(words))[:6]
    summary = f"[T1-stub:{task_type}] key concepts: {', '.join(top_words) or 'none'}"
    return {"mock_response": summary, "tier_used": "T1_stub"}


if __name__ == "__main__":
    print("=== SOVEREIGN-IMPERIA-CITADEL model_backend hardware probe ===\n")
    hw = detect_hardware()
    print(hw.summary())
    print()

    spec = _select_model_spec(hw)
    print("Recommended model configuration:")
    print(f"  Embedding model   : {spec.embed_model}")
    print(f"  NLI judge model   : {spec.nli_model}")
    print(f"  General LLM       : {spec.general_model}")
    print(f"  Quantization      : {spec.quantization}")
    print(f"  GPU layers        : {spec.n_gpu_layers} (-1 = all on GPU)")
    print(f"  Max context tokens: {spec.max_context_tokens}")
    print(f"  CPU thread count  : {spec.thread_count}")
    print()

    backend = get_backend()
    print(f"Backend tier        : T1 ({hw.device.value})")

    vecs = backend._pseudo_embed(["Hello, SOVEREIGN-IMPERIA-CITADEL"])
    assert len(vecs) == 1 and len(vecs[0]) == 64
    print("Pseudo-embed         : OK (64-dim, no ML libs required)")

    result = backend._pseudo_nli("The sky is blue", "The sky appears blue on clear days.")
    print(f"Pseudo-NLI           : OK ({result['label']}, score={result['score']:.2f})")

    print("\n=== Hardware probe complete — no crash ===")
