"""Hardware detection in tools/model_backend — regression guard for the cross-platform RAM/GPU probes
and the tier-ladder spec selection (the importlib.util / Windows-RAM / nvidia-smi bugs)."""

import sys
from pathlib import Path

import pytest

_TOOLS = str(Path(__file__).resolve().parents[1] / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import model_backend as mb  # noqa: E402


def test_detect_hardware_returns_profile_without_crash():
    hw = mb.detect_hardware()
    assert isinstance(hw, mb.HardwareProfile)
    assert hw.cpu_count >= 1
    assert isinstance(hw.summary(), str)


def test_system_memory_bytes_positive_on_this_host():
    total, avail = mb._system_memory_bytes()
    assert total > 0
    assert 0 <= avail <= total


def test_probe_total_ram_positive():
    assert mb._probe_total_ram_gb() > 0


@pytest.mark.parametrize("device", list(mb.BackendDevice))
def test_select_model_spec_covers_every_tier(device):
    vram = 24.0 if "CUDA" in device.name else 0.0
    hw = mb.HardwareProfile(device=device, cpu_count=8, total_ram_gb=32.0, available_ram_gb=16.0, vram_gb=vram)
    spec = mb._select_model_spec(hw)
    assert spec.general_model
    assert spec.max_context_tokens > 0
    assert spec.thread_count >= 1


def test_gpu_tiers_offload_layers():
    for device, vram in [
        (mb.BackendDevice.CUDA_FULL, 24.0),
        (mb.BackendDevice.CUDA_SPLIT, 8.0),
        (mb.BackendDevice.MPS, 0.0),
    ]:
        hw = mb.HardwareProfile(device=device, cpu_count=8, total_ram_gb=32.0, available_ram_gb=16.0, vram_gb=vram)
        assert mb._select_model_spec(hw).n_gpu_layers != 0


def test_cpu_tiers_have_no_gpu_offload():
    for device in (mb.BackendDevice.CPU_ADEQUATE, mb.BackendDevice.CPU_CONSTRAINED):
        hw = mb.HardwareProfile(device=device, cpu_count=8, total_ram_gb=32.0, available_ram_gb=16.0, vram_gb=0.0)
        assert mb._select_model_spec(hw).n_gpu_layers == 0


def test_nvidia_smi_probe_shape():
    result = mb._probe_nvidia_smi()
    if result is None:
        pytest.skip("no NVIDIA GPU / nvidia-smi on this host")
    vram_gb, name = result
    assert vram_gb > 0
    assert isinstance(name, str) and name


def test_resolve_gguf_raises_filenotfound_not_nameerror():
    backend = mb.get_backend()
    with pytest.raises(FileNotFoundError):
        backend._resolve_gguf_path("definitely-not-a-real-model.gguf")
