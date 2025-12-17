from ..qt_compat import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QProgressBar, 
    Qt, QSizePolicy, QFrame, QPushButton
)
from ..resource_monitor import ResourceMonitor

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
        
        # Use Grid layout to align columns (CPU/GPU, RAM/VRAM)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(2)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        # Row 0: CPU and RAM
        self.cpu_bar = CompactResourceBar("CPU")
        self.grid.addWidget(self.cpu_bar, 0, 0)
        
        self.ram_bar = CompactResourceBar("RAM")
        self.grid.addWidget(self.ram_bar, 0, 1)
        
        # Flush VRAM Button (Row 0, Col 2) - spans 2 rows
        self.flush_btn = QPushButton("Flush")
        self.flush_btn.setToolTip("Force ComfyUI to unload models and free VRAM")
        self.flush_btn.setFixedWidth(40)
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
        """)
        self.flush_btn.clicked.connect(self._flush_vram)
        self.grid.addWidget(self.flush_btn, 0, 2, 2, 1) # Span 2 rows
        
        # GPU widgets storage
        self.gpu_widgets = {} # index -> (core_bar, vram_bar)
        
        self.monitor.start()

    def _flush_vram(self):
        """Call ComfyUI's /free endpoint to unload models."""
        from ..config import COMFY_URL_BASE
        import urllib.request
        
        url = f"{COMFY_URL_BASE}/free"
        req = urllib.request.Request(url, method="POST")
        # Empty JSON body required by some endpoints, usually safe to send
        req.add_header('Content-Type', 'application/json')
        
        try:
            with urllib.request.urlopen(req, data=b'{"unload_models":true, "free_memory":true}', timeout=2) as response:
                if response.getcode() == 200:
                    # Flash button green briefly
                    self.flush_btn.setStyleSheet(self.flush_btn.styleSheet().replace("#37383D", "#2E7D32"))
                    from ..qt_compat import QTimer
                    QTimer.singleShot(500, lambda: self.flush_btn.setStyleSheet(self.flush_btn.styleSheet().replace("#2E7D32", "#37383D")))
        except Exception as e:
            from ..charon_logger import system_error
            system_error(f"Failed to flush VRAM: {e}")
            # Flash button red briefly
            self.flush_btn.setStyleSheet(self.flush_btn.styleSheet().replace("#37383D", "#C62828"))
            from ..qt_compat import QTimer
            QTimer.singleShot(500, lambda: self.flush_btn.setStyleSheet(self.flush_btn.styleSheet().replace("#C62828", "#37383D")))

    def update_stats(self, stats):
        self.cpu_bar.set_value(stats['cpu_percent'])
        
        ram_p = stats['ram_percent']
        ram_txt = f"RAM: {stats['ram_used_gb']:.1f}GB / {stats['ram_total_gb']:.1f}GB ({ram_p:.1f}%)"
        self.ram_bar.set_value(ram_p, ram_txt)
        
        gpus = stats.get('gpus', [])
        
        # Create widgets for GPUs if they don't exist
        for i, gpu in enumerate(gpus):
            idx = gpu['index']
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

    def closeEvent(self, event):
        self.monitor.stop()
        super().closeEvent(event)
