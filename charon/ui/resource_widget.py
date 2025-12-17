from ..qt_compat import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QProgressBar, 
    Qt, QSizePolicy, QFrame, QPushButton, QObject, Signal, QThread, QTimer
)
from ..resource_monitor import ResourceMonitor

class FlushWorker(QObject):
    finished = Signal(bool)

    def run(self):
        from ..config import COMFY_URL_BASE
        import urllib.request
        
        url = f"{COMFY_URL_BASE}/free"
        req = urllib.request.Request(url, method="POST")
        req.add_header('Content-Type', 'application/json')
        
        try:
            with urllib.request.urlopen(req, data=b'{"unload_models":true, "free_memory":true}', timeout=5) as response:
                self.finished.emit(response.getcode() == 200)
        except Exception:
            self.finished.emit(False)

class CompactResourceBar(QWidget):
    def __init__(self, label_text, color="#4CAF50", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(4)
        
        self.label = QLabel(label_text)
        self.label.setStyleSheet("color: #aaa; font-size: 10px; font-weight: bold;")
        self.label.setFixedWidth(32) # Fixed width for alignment
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.label)
        
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setFixedWidth(50)
        # Default style
        self.default_color = color
        self.update_style(0)
        
        layout.addWidget(self.bar)
        
        # self.value_label removed per request

    def update_style(self, value):
        color = self.default_color
        if value > 90:
            color = "#F44336" # Red
        elif value > 75:
            color = "#FFC107" # Amber
            
        self.bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid #444;
                border-radius: 2px;
                background-color: #222;
            }}
            QProgressBar::chunk {{
                background-color: {color};
            }}
        """)

    def set_value(self, value, tooltip_text=None):
        self.bar.setValue(int(value))
        if tooltip_text:
            self.setToolTip(tooltip_text)
            self.bar.setToolTip(tooltip_text)
        else:
            txt = f"{int(value)}%"
            self.setToolTip(txt)
            self.bar.setToolTip(txt)
            
        self.update_style(value)

class ResourceWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.monitor = ResourceMonitor(self)
        self.monitor.stats_updated.connect(self.update_stats)
        self.current_total_vram_gb = 0
        
        # Use Grid layout to align columns (CPU/GPU, RAM/VRAM)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(4) # Reduced from 8 to bring label closer
        self.grid.setVerticalSpacing(2)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        # Row 0: CPU and RAM
        self.cpu_bar = CompactResourceBar("CPU")
        self.grid.addWidget(self.cpu_bar, 0, 0)
        
        self.ram_bar = CompactResourceBar("RAM")
        self.grid.addWidget(self.ram_bar, 0, 1)
        
        # Flush VRAM Button (Row 0, Col 2) - spans 2 rows
        self.flush_btn = QPushButton("🧹 VRAM")
        self.flush_btn.setToolTip("Force ComfyUI to unload models and free VRAM")
        self.flush_btn.setFixedWidth(60)
        self.flush_btn.setFixedHeight(24) # Match approximate height of 2 rows
        self.flush_btn.setCursor(Qt.PointingHandCursor)
        self.flush_btn.setStyleSheet("""
            QPushButton {
                background-color: #37383D;
                color: #cfd3dc;
                border: 1px solid #2c323c;
                border-radius: 3px;
                font-size: 10px;
                margin-left: 4px;
            }
            QPushButton:hover {
                background-color: #404248;
                border-color: #555;
            }
            QPushButton:pressed {
                background-color: #2f3034;
            }
            QPushButton:disabled {
                color: #7f848e;
                background-color: #2c323c;
            }
        """)
        self.flush_btn.clicked.connect(self._flush_vram)
        self.grid.addWidget(self.flush_btn, 0, 2, 2, 1) # Span 2 rows
        
        # Feedback Label (Row 0, Col 3) - spans 2 rows
        self.flush_feedback = QLabel("")
        self.flush_feedback.setStyleSheet("color: #cfd3dc; font-size: 10px; margin-left: 0px;")
        self.flush_feedback.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.grid.addWidget(self.flush_feedback, 0, 3, 2, 1)
        
        # GPU widgets storage
        self.gpu_widgets = {} # index -> (core_bar, vram_bar)
        
        # Animation state
        self.anim_dots = 0
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._update_anim)
        
        self.monitor.start()

    def _update_anim(self):
        self.anim_dots = (self.anim_dots % 3) + 1
        self.flush_feedback.setText(f"Flushing{'.' * self.anim_dots}")

    def _flush_vram(self):
        self.pre_flush_vram = self.current_total_vram_gb
        self.flush_btn.setEnabled(False)
        self.flush_feedback.setText("Flushing...")
        self.anim_dots = 0
        self.anim_timer.start(300)
        
        from ..charon_logger import system_debug
        system_debug(f"Flushing VRAM. Pre-flush usage: {self.pre_flush_vram:.2f} GB")
        
        self.worker = FlushWorker()
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._on_flush_finished)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.start()

    def _on_flush_finished(self, success):
        if success:
            self._start_result_polling()
        else:
            self.anim_timer.stop()
            self.flush_feedback.setText("Failed")
            self.flush_btn.setEnabled(True)
            QTimer.singleShot(4000, lambda: self.flush_feedback.setText(""))

    def _start_result_polling(self):
        # Start polling for result update
        self.result_timer = QTimer(self)
        self.result_timer.timeout.connect(self._update_result_display)
        self.result_timer.start(200) # Check every 200ms
        
        # Stop polling after 5 seconds
        QTimer.singleShot(5000, self._finish_result_polling)

    def _update_result_display(self):
        diff = max(0, self.pre_flush_vram - self.current_total_vram_gb)
        # Only show if we detect a drop > 50MB
        if diff > 0.05:
            self.anim_timer.stop()
            self.flush_feedback.setText(f"Freed {diff:.2f}GB")

    def _finish_result_polling(self):
        if hasattr(self, 'result_timer'):
            self.result_timer.stop()
            self.result_timer.deleteLater()
            del self.result_timer
        
        self.anim_timer.stop()
        
        # Final check / fallback
        diff = max(0, self.pre_flush_vram - self.current_total_vram_gb)
        self.flush_feedback.setText(f"Freed {diff:.2f}GB")
            
        self.flush_btn.setEnabled(True)
        # Clear text after a delay
        QTimer.singleShot(2000, lambda: self.flush_feedback.setText(""))

    def update_stats(self, stats):
        self.cpu_bar.set_value(stats['cpu_percent'])
        
        ram_p = stats['ram_percent']
        ram_txt = f"RAM: {stats['ram_used_gb']:.1f}GB / {stats['ram_total_gb']:.1f}GB ({ram_p:.1f}%)"
        self.ram_bar.set_value(ram_p, ram_txt)
        
        gpus = stats.get('gpus', [])
        
        total_vram_used = 0
        
        # Create widgets for GPUs if they don't exist
        for i, gpu in enumerate(gpus):
            idx = gpu['index']
            
            total_vram_used += gpu.get('vram_used_gb', 0)
            
            if idx not in self.gpu_widgets:
                core_bar = CompactResourceBar(f"GPU", color="#00BCD4")
                vram_bar = CompactResourceBar(f"VRAM", color="#9C27B0")
                
                # Add to grid at Row 1 + i
                row = 1 + i
                self.grid.addWidget(core_bar, row, 0)
                self.grid.addWidget(vram_bar, row, 1)
                
                self.gpu_widgets[idx] = (core_bar, vram_bar)
            
            core, vram = self.gpu_widgets[idx]
            core.set_value(gpu['utilization'], f"GPU Usage: {gpu['utilization']}%")
            
            vram_p = gpu['vram_percent']
            vram_txt = f"VRAM: {gpu['vram_used_gb']:.1f}GB / {gpu['vram_total_gb']:.1f}GB ({vram_p:.1f}%)"
            vram.set_value(vram_p, vram_txt)
            
        self.current_total_vram_gb = total_vram_used

    def closeEvent(self, event):
        self.monitor.stop()
        super().closeEvent(event)

    def restart_monitor(self):
        """Restart the resource monitor thread."""
        if self.monitor:
            self.monitor.stop()
        # Re-create and start
        self.monitor = ResourceMonitor(self)
        self.monitor.stats_updated.connect(self.update_stats)
        self.monitor.start()
