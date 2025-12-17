import time
import psutil
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
        if HAS_PYNVML:
            try:
                pynvml.nvmlInit()
                self.pynvml_initialized = True
            except Exception as e:
                system_error(f"Failed to initialize pynvml: {e}")

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
                        "temperature": temp
                    })
            except Exception as e:
                # system_error(f"Error reading GPU stats: {e}")
                pass

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
