from ..qt_compat import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QProgressBar, 
    Qt, QSizePolicy, QFrame
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
        
        self.value_label = QLabel("0%")
        self.value_label.setStyleSheet("color: #ccc; font-size: 10px;")
        self.value_label.setFixedWidth(35)
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.value_label)

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

    def set_value(self, value, text_override=None):
        self.bar.setValue(int(value))
        self.value_label.setText(text_override if text_override else f"{int(value)}%")
        self.update_style(value)

class ResourceWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.monitor = ResourceMonitor(self)
        self.monitor.stats_updated.connect(self.update_stats)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # CPU
        self.cpu_bar = CompactResourceBar("CPU")
        layout.addWidget(self.cpu_bar)
        
        # RAM
        self.ram_bar = CompactResourceBar("RAM")
        layout.addWidget(self.ram_bar)
        
        # GPU/VRAM (Dynamic)
        self.gpu_widgets = {} # index -> (core_bar, vram_bar)
        self.gpu_container = QWidget()
        self.gpu_layout = QHBoxLayout(self.gpu_container)
        self.gpu_layout.setContentsMargins(0, 0, 0, 0)
        self.gpu_layout.setSpacing(8)
        layout.addWidget(self.gpu_container)
        
        self.monitor.start()

    def update_stats(self, stats):
        self.cpu_bar.set_value(stats['cpu_percent'])
        
        ram_p = stats['ram_percent']
        ram_gb = f"{stats['ram_used_gb']:.1f}G"
        self.ram_bar.set_value(ram_p, ram_gb)
        
        gpus = stats.get('gpus', [])
        
        # Create widgets for GPUs if they don't exist
        for gpu in gpus:
            idx = gpu['index']
            if idx not in self.gpu_widgets:
                core_bar = CompactResourceBar(f"GPU", color="#00BCD4")
                vram_bar = CompactResourceBar(f"VRAM", color="#9C27B0")
                
                self.gpu_layout.addWidget(core_bar)
                self.gpu_layout.addWidget(vram_bar)
                
                self.gpu_widgets[idx] = (core_bar, vram_bar)
            
            core, vram = self.gpu_widgets[idx]
            core.set_value(gpu['utilization'])
            
            vram_p = gpu['vram_percent']
            vram_txt = f"{gpu['vram_used_gb']:.1f}G"
            vram.set_value(vram_p, vram_txt)

    def closeEvent(self, event):
        self.monitor.stop()
        super().closeEvent(event)
