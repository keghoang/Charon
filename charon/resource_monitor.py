import time
import psutil
import subprocess
import shutil
from .qt_compat import QObject, Signal, QThread
from .charon_logger import system_error, system_debug

# Try importing pynvml for GPU stats
try:
    import pynvml
    HAS_PYNVML = True
except ImportError:
    HAS_PYNVML = False

class HardwareInfo:
    def __init__(self):
        self.pynvml_initialized = False
        self.nvidia_smi_path = shutil.which("nvidia-smi")
        
        if HAS_PYNVML:
            try:
                pynvml.nvmlInit()
                self.pynvml_initialized = True
            except Exception as e:
                system_error(f"Failed to initialize pynvml: {e}")

    def _is_supported_gpu(self, name: str) -> bool:
        """
        Check if the GPU is a supported GeForce RTX 30xx/40xx/50xx card.
        Ignores A2000, 20xx series, and non-GeForce cards.
        """
        if not name:
            return False
        
        name_clean = name.strip()
        if "GeForce RTX" not in name_clean:
            return False
            
        import re
        # Match 30xx, 40xx, 50xx
        # \b ensures we match "3060" but not "1030" or similar false positives if they existed
        return bool(re.search(r"\b(30|40|50)\d{2}\b", name_clean))

    def _get_gpu_stats_nvidia_smi(self):
        """Fallback to nvidia-smi if pynvml is unavailable"""
        if not self.nvidia_smi_path:
            return []
            
        try:
            # query: utilization.gpu [%], memory.total [MiB], memory.used [MiB], name
            cmd = [
                self.nvidia_smi_path,
                "--query-gpu=utilization.gpu,memory.total,memory.used,name",
                "--format=csv,noheader,nounits"
            ]
            # Use a short timeout to prevent UI freeze
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True, timeout=1.0
            )
            
            stats = []
            for i, line in enumerate(result.stdout.strip().splitlines()):
                parts = [p.strip() for p in line.split(',')]
                if len(parts) < 4:
                    continue
                    
                util = float(parts[0])
                total_mb = float(parts[1])
                used_mb = float(parts[2])
                name = parts[3]
                
                if not self._is_supported_gpu(name):
                    continue
                
                vram_percent = (used_mb / total_mb * 100) if total_mb > 0 else 0
                
                stats.append({
                    "index": i,
                    "utilization": util,
                    "vram_percent": vram_percent,
                    "vram_used_gb": used_mb / 1024,
                    "vram_total_gb": total_mb / 1024,
                    "temperature": 0, # Not queried to keep it simple
                    "name": name
                })
            return stats
        except Exception:
            return []

    def get_status(self):
        # CPU
        cpu = psutil.cpu_percent(interval=None)
        
        # RAM
        ram = psutil.virtual_memory()
        ram_used_percent = ram.percent
        ram_total_gb = ram.total / (1024**3)
        ram_used_gb = ram.used / (1024**3)

        # GPU
        gpu_stats = []
        if self.pynvml_initialized:
            try:
                device_count = pynvml.nvmlDeviceGetCount()
                for i in range(device_count):
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    
                    # Name check
                    try:
                        name_raw = pynvml.nvmlDeviceGetName(handle)
                        if isinstance(name_raw, bytes):
                            name = name_raw.decode("utf-8")
                        else:
                            name = str(name_raw)
                    except Exception:
                        name = "Unknown GPU"
                    
                    if not self._is_supported_gpu(name):
                        continue
                    
                    # Utilization
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
                    
                    # Memory
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    vram_total = mem_info.total
                    vram_used = mem_info.used
                    vram_percent = (vram_used / vram_total) * 100 if vram_total > 0 else 0
                    
                    # Temp
                    temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                    
                    gpu_stats.append({
                        "index": i,
                        "utilization": util,
                        "vram_percent": vram_percent,
                        "vram_used_gb": vram_used / (1024**3),
                        "vram_total_gb": vram_total / (1024**3),
                        "temperature": temp,
                        "name": name
                    })
            except Exception as e:
                # Fallback if runtime error occurs
                self.pynvml_initialized = False
                gpu_stats = self._get_gpu_stats_nvidia_smi()
        else:
            gpu_stats = self._get_gpu_stats_nvidia_smi()

        return {
            "cpu_percent": cpu,
            "ram_percent": ram_used_percent,
            "ram_used_gb": ram_used_gb,
            "ram_total_gb": ram_total_gb,
            "gpus": gpu_stats
        }

class ResourceMonitorWorker(QObject):
    stats_ready = Signal(dict)
    finished = Signal()

    def __init__(self, rate=1.0):
        super().__init__()
        self.rate = rate
        self.running = True
        self.hardware = HardwareInfo()

    def run(self):
        while self.running:
            try:
                stats = self.hardware.get_status()
                self.stats_ready.emit(stats)
            except Exception as e:
                system_error(f"Resource monitor error: {e}")
            
            # Sleep in small chunks to allow quick stopping
            for _ in range(int(self.rate * 10)):
                if not self.running:
                    break
                time.sleep(0.1)
        self.finished.emit()

    def stop(self):
        self.running = False

class ResourceMonitor(QObject):
    """
    Controller for the background worker.
    """
    stats_updated = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread = QThread()
        self.worker = ResourceMonitorWorker()
        self.worker.moveToThread(self.thread)
        
        self.thread.started.connect(self.worker.run)
        self.worker.stats_ready.connect(self.stats_updated)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

    def start(self):
        self.thread.start()

    def stop(self):
        self.worker.stop()
        self.thread.quit()
        self.thread.wait()
