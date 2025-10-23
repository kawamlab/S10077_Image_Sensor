import sys
import serial
import serial.tools.list_ports
import numpy as np
import threading

from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QLabel, QGridLayout
from PySide6.QtCore import Signal, QObject
import pyqtgraph as pg

# ===== Configuration =====
BAUD_RATE = 115200
NUM_PIXELS = 1024
BEGIN_TOKEN = 'BEGIN,'
END_TOKEN = 'END'
SERIAL_ENCODING = 'utf-8'
READ_TIMEOUT_S = 0.1

# ===== Qt signal bridge =====
class Communication(QObject):
    spec_data_ready = Signal(int, np.ndarray)

# ---------- Parser ----------
def parse_spectrum_frame(line: str):
    line = line.strip()
    if not line.startswith(BEGIN_TOKEN) or not line.endswith(END_TOKEN):
        return None
    try:
        payload = line[len(BEGIN_TOKEN):-len(END_TOKEN)].rstrip(',')
        if not payload: return None
        parts = payload.split(',')
        sensor_id = int(parts[0].split('_')[1])
        data_string = ','.join(parts[1:])
        arr = np.fromstring(data_string, sep=',', dtype=np.uint16)
        if arr.size != NUM_PIXELS:
            return None
        return sensor_id, arr
    except (ValueError, IndexError):
        return None

# ---------- Serial reader ----------
def serial_reader_thread(ser: serial.Serial, comm: Communication, stop_event: threading.Event):
    print("Serial reader thread started...")
    while not stop_event.is_set():
        if not ser or not ser.is_open: break
        try:
            line_bytes = ser.readline()
            if not line_bytes: continue
            line = line_bytes.decode(SERIAL_ENCODING, errors='ignore')
            parse_result = parse_spectrum_frame(line)
            if parse_result:
                sensor_id, spectrum_data = parse_result
                comm.spec_data_ready.emit(sensor_id, spectrum_data)
        except Exception:
            break
    print("Serial reader thread exited.")

# ---------- Spectral coloring helper ----------
def wavelength_to_rgb(wavelength, gamma=0.8):
    wavelength = float(wavelength)
    if 380 <= wavelength <= 440:
        attenuation = 0.3 + 0.7 * (wavelength - 380) / (440 - 380)
        R = ((-(wavelength - 440) / (440 - 380)) * attenuation) ** gamma
        G = 0.0
        B = (1.0 * attenuation) ** gamma
    elif 440 < wavelength <= 490:
        R, G, B = 0.0, ((wavelength - 440) / (490 - 440)) ** gamma, 1.0
    elif 490 < wavelength <= 510:
        R, G, B = 0.0, 1.0, (-(wavelength - 510) / (510 - 490)) ** gamma
    elif 510 < wavelength <= 580:
        R, G, B = ((wavelength - 510) / (580 - 510)) ** gamma, 1.0, 0.0
    elif 580 < wavelength <= 645:
        R, G, B = 1.0, (-(wavelength - 645) / (645 - 580)) ** gamma, 0.0
    elif 645 < wavelength <= 750:
        attenuation = 0.3 + 0.7 * (750 - wavelength) / (750 - 645)
        R, G, B = (1.0 * attenuation) ** gamma, 0.0, 0.0
    else:
        R = G = B = 0.5
    return (int(R*255), int(G*255), int(B*255))

def generate_spectral_brushes():
    sensitivity_wl = np.array([400, 450, 500, 550, 600, 650, 700, 800, 900, 1000])
    sensitivity_val = np.array([0.5, 0.85, 0.8, 1.0, 0.82, 0.92, 0.85, 0.45, 0.2, 0.05])
    wavelengths = np.linspace(400, 1000, NUM_PIXELS)
    interpolated_sensitivity = np.interp(wavelengths, sensitivity_wl, sensitivity_val)
    brushes = []
    for i, wl in enumerate(wavelengths):
        base_rgb = wavelength_to_rgb(wl)
        sensitivity = interpolated_sensitivity[i]
        final_rgb = [int(c * sensitivity) for c in base_rgb]
        brushes.append(pg.mkBrush(color=final_rgb))
    return brushes

# ---------- Main window ----------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('S10077 Visualizer (Monochrome Mode)')
        self.setGeometry(100, 100, 1400, 800)

        self.ser = None
        self.serial_thread = None
        self.stop_event = threading.Event()
        self.comm = Communication()
        
        self.plot_widgets = {}
        self.bar_items = {}
        self.spectral_brushes = generate_spectral_brushes()

        # --- 新增模式控制 ---
        self.spec_mode = False  # 默认单色

        self.init_ui()
        self.connect_signals()
        self.refresh_ports()
        self.setup_plot_layout("1 Sensor")

    def init_ui(self):
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        top_control_layout = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(250)
        self.refresh_btn = QPushButton("Refresh")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setCheckable(True)
        self.status_label = QLabel("Select a serial port and connect")

        # --- 新增显示模式选项 ---
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Monochrome", "Spectral"])

        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["1 Sensor", "2 Sensors", "3 Sensors", "4 Sensors"])
        top_control_layout.addWidget(QLabel("Layout:"))
        top_control_layout.addWidget(self.layout_combo)
        top_control_layout.addSpacing(15)
        top_control_layout.addWidget(QLabel("Mode:"))
        top_control_layout.addWidget(self.mode_combo)
        top_control_layout.addSpacing(20)

        top_control_layout.addWidget(QLabel("Serial Port:"))
        top_control_layout.addWidget(self.port_combo)
        top_control_layout.addWidget(self.refresh_btn)
        top_control_layout.addWidget(self.connect_btn)
        top_control_layout.addStretch()
        top_control_layout.addWidget(self.status_label)
        main_layout.addLayout(top_control_layout)

        plot_container = QWidget()
        self.grid_layout = QGridLayout(plot_container)
        main_layout.addWidget(plot_container)

        self.focus_combo = QComboBox()
        self.focus_combo.addItems(["None", "Sensor 0", "Sensor 1", "Sensor 2"])
        top_control_layout.addSpacing(15)
        top_control_layout.addWidget(QLabel("Focus:"))
        top_control_layout.addWidget(self.focus_combo)


    def switch_mode(self, text):
        """切换显示模式"""
        self.spec_mode = (text == "Spectral")
        self.setup_plot_layout(self.layout_combo.currentText())

    def setup_plot_layout(self, layout_text: str):
        # 清空旧布局
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget: widget.deleteLater()
        self.plot_widgets.clear()
        self.bar_items.clear()

        num_sensors = int(layout_text.split(' ')[0])
        wavelengths = np.linspace(400, 1000, NUM_PIXELS)

        # === 自动布局逻辑 ===
        if num_sensors == 1:
            rows, cols = 1, 1
        elif num_sensors == 2:
            rows, cols = 1, 2
        else:
            rows, cols = 2, 2  # 3和4都用2x2网格，留一格空白时自动对齐

        sensor_id = 0
        for r in range(rows):
            for c in range(cols):
                if sensor_id >= num_sensors:
                    # 插入空白Widget占位，防止显示错位
                    placeholder = QWidget()
                    self.grid_layout.addWidget(placeholder, r, c)
                    continue

                plot_widget = pg.PlotWidget()
                plot_widget.setTitle(f"Sensor {sensor_id}", color='w', size='12pt')
                plot_widget.setLabel('bottom', 'Pixel index' if not self.spec_mode else 'Wavelength (nm)')
                plot_widget.setLabel('left', 'Intensity (12-bit ADC)')
                plot_widget.setYRange(0, 4095)
                plot_widget.showGrid(x=True, y=True, alpha=0.3)

                # === 禁用平移、菜单，只保留缩放 ===
                view_box = plot_widget.getViewBox()
                view_box.setMouseEnabled(pg.ViewBox.RectMode)  # 禁用拖动
                plot_widget.setMenuEnabled(False)  # 禁用右键菜单
                view_box.setAspectLocked(False)  # 防止比例锁死
                view_box.setLimits(xMin=None, xMax=None, yMin=0, yMax=4095)  # 限定范围

                brushes = (self.spectral_brushes if self.spec_mode
                        else [pg.mkBrush(color=(200, 200, 255))] * NUM_PIXELS)

                bar_item = pg.BarGraphItem(
                    x=wavelengths if self.spec_mode else np.arange(NUM_PIXELS),
                    height=np.zeros(NUM_PIXELS),
                    width=1 if not self.spec_mode else (wavelengths[1]-wavelengths[0])*0.9,
                    brushes=brushes
                )
                plot_widget.addItem(bar_item)

                # === 确保固定比例 ===
                plot_widget.setAspectLocked(lock=False, ratio=None)

                self.grid_layout.addWidget(plot_widget, r, c)
                self.plot_widgets[sensor_id] = plot_widget
                self.bar_items[sensor_id] = bar_item
                sensor_id += 1


    def update_plot(self, sensor_id: int, data_array: np.ndarray):
        if sensor_id in self.bar_items:
            self.bar_items[sensor_id].setOpts(height=data_array)

    def connect_signals(self):
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.comm.spec_data_ready.connect(self.update_plot)
        self.layout_combo.currentTextChanged.connect(self.setup_plot_layout)
        self.mode_combo.currentTextChanged.connect(self.switch_mode)
        self.focus_combo.currentTextChanged.connect(lambda _: self.setup_plot_layout(self.layout_combo.currentText()))


    def refresh_ports(self):
        """刷新可用串口列表"""
        import serial.tools.list_ports
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(port.device)
        if not ports:
            self.port_combo.addItem("No ports found")

    def toggle_connection(self, checked):
        if checked:
            port_full_name = self.port_combo.currentText()
            if not port_full_name:
                self.status_label.setText("Error: No serial port selected")
                self.connect_btn.setChecked(False)
                return
            port_device = port_full_name.split(' - ')[0]
            try:
                self.ser = serial.Serial(port_device, BAUD_RATE, timeout=READ_TIMEOUT_S)
                self.stop_event.clear()
                self.serial_thread = threading.Thread(target=serial_reader_thread, args=(self.ser, self.comm, self.stop_event))
                self.serial_thread.start()
                self.connect_btn.setText("Disconnect")
                self.status_label.setText(f"Connected to {port_device}")
            except Exception as e:
                self.status_label.setText(f"Connection failed: {e}")
                self.connect_btn.setChecked(False)
        else:
            self.stop_event.set()
            if self.serial_thread and self.serial_thread.is_alive():
                self.serial_thread.join(timeout=1.0)
            if self.ser and self.ser.is_open:
                self.ser.close()
            self.ser = None
            self.connect_btn.setText("Connect")
            self.status_label.setText("Disconnected")

    def closeEvent(self, event):
        self.stop_event.set()
        if self.serial_thread and self.serial_thread.is_alive():
            self.serial_thread.join(timeout=1.0)
        if self.ser and self.ser.is_open:
            self.ser.close()
        event.accept()

# ---------- Entrypoint ----------
if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
