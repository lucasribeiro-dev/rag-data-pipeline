import os
import subprocess
import psutil


# Approximate memory per Whisper model (GB) — RAM and VRAM each
WHISPER_MODEL_MEMORY = {
    "tiny": 1.0,
    "base": 1.5,
    "small": 2.5,
    "medium": 5.0,
    "large": 10.0,
    "large-v2": 10.0,
    "large-v3": 10.0,
}


def get_resources():
    """Snapshot of current system resources."""
    mem = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "cpu_count": os.cpu_count(),
        "ram_total_gb": round(mem.total / (1024 ** 3), 1),
        "ram_available_gb": round(mem.available / (1024 ** 3), 1),
        "ram_percent": mem.percent,
        "gpu": _get_gpu_info(),
    }


def _get_gpu_info():
    """Get GPU VRAM via nvidia-smi (no CUDA init, safe before fork/spawn)."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None

        gpus = []
        for line in result.stdout.strip().split("\n"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 3:
                gpus.append({
                    "name": parts[0],
                    "total_gb": round(float(parts[1]) / 1024, 1),
                    "free_gb": round(float(parts[2]) / 1024, 1),
                })
        return gpus if gpus else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def gpu_has_room(model_name):
    """Check if GPU currently has enough free VRAM for one more model."""
    gpu = _get_gpu_info()
    if not gpu:
        return False
    model_mem = WHISPER_MODEL_MEMORY.get(model_name, 2.0)
    return gpu[0]["free_gb"] > model_mem + 1.0


def can_add_worker(model_name, current_workers=0):
    """Check if system has enough RAM + CPU for a CPU worker.

    GPU is handled per-worker at spawn time (pick_device), not here.
    The scaler only gates on RAM and CPU since extra workers use CPU.

    Returns (bool, reason_string).
    """
    res = get_resources()
    model_mem = WHISPER_MODEL_MEMORY.get(model_name, 2.0)

    # RAM: need model_mem + 2GB buffer
    ram_needed = model_mem + 2.0
    if res["ram_available_gb"] < ram_needed:
        return False, f"RAM: {res['ram_available_gb']:.1f}GB free, need {ram_needed:.1f}GB"

    # CPU: stay below 85%
    if res["cpu_percent"] > 85:
        return False, f"CPU: {res['cpu_percent']:.0f}% used, need <85%"

    return True, "ok"


def estimate_max_workers(model_name):
    """Calculate how many workers the system can handle.

    Accounts for 1 GPU worker + N CPU workers based on available RAM.
    """
    res = get_resources()
    model_mem = WHISPER_MODEL_MEMORY.get(model_name, 2.0)

    # GPU worker: 1 if model fits, uses VRAM (not RAM)
    gpu_workers = 1 if gpu_has_room(model_name) else 0

    # CPU workers: based on available RAM (keep 4GB for system)
    ram_free = max(0, res["ram_available_gb"] - 4.0)
    cpu_workers = int(ram_free / model_mem)

    # CPU core limit (~1 worker per 2 cores, leave headroom)
    core_limit = max(1, res["cpu_count"] // 2)
    cpu_workers = min(cpu_workers, core_limit)

    max_w = gpu_workers + cpu_workers
    return max(1, max_w), res
