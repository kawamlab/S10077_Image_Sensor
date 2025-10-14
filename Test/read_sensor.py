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

# ---------- Parser (No changes needed) ----------
def parse_spectrum_frame(line: str):
    line = line.strip()
    if not line.startswith(BEGIN_TOKEN) or not line.endswith(END_TOKEN): return None
    try:
        payload = line[len(BEGIN_TOKEN):-len(END_TOKEN)].rstrip(',')
        if not payload: return None
        parts = payload.split(',')
        sensor_id = int(parts[0].split('_')[1])
        data_string = ','.join(parts[1:])
        arr = np.fromstring(data_string, sep=',', dtype=np.uint16)
        if arr.size != NUM_PIXELS: return None
        return sensor_id, arr
    except (ValueError, IndexError):
        return None

# ---------- Serial reader thread (No changes needed) ----------
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

# --- MAJOR NEW FEATURE: Data-driven spectral color generation ---
def wavelength_to_rgb(wavelength, gamma=0.8):
    """Converts a given wavelength in nm to an approximate RGB color tuple."""
    wavelength = float(wavelength)
    if 380 <= wavelength <= 440:
        attenuation = 0.3 + 0.7 * (wavelength - 380) / (440 - 380)
        R = ((-(wavelength - 440) / (440 - 380)) * attenuation) ** gamma
        G = 0.0
        B = (1.0 * attenuation) ** gamma
    elif 440 < wavelength <= 490:
        R = 0.0
        G = ((wavelength - 440) / (490 - 440)) ** gamma
        B = 1.0
    elif 490 < wavelength <= 510:
        R = 0.0
        G = 1.0
        B = (-(wavelength - 510) / (510 - 490)) ** gamma
    elif 510 < wavelength <= 580:
        R = ((wavelength - 510) / (580 - 510)) ** gamma
        G = 1.0
        B = 0.0
    elif 580 < wavelength <= 645:
        R = 1.0
        G = (-(wavelength - 645) / (645 - 580)) ** gamma
        B = 0.0
    elif 645 < wavelength <= 750:
        attenuation = 0.3 + 0.7 * (750 - wavelength) / (750 - 645)
        R = (1.0 * attenuation) ** gamma
        G = 0.0
        B = 0.0
    else: # Infrared/Ultraviolet are shown as gray
        R, G, B = 0.5, 0.5, 0.5
    return (int(R*255), int(G*255), int(B*255))

def generate_spectral_brushes():
    """
    Generates brushes for the bar graph based on the S10077's spectral sensitivity.
    Colors are based on wavelength, and brightness is modulated by sensitivity.
    """
    # Key data points extracted from the S10077 datasheet, page 3 graph
    sensitivity_wl = np.array([400, 450, 500, 550, 600, 650, 700, 800, 900, 1000, 1100])
    sensitivity_val = np.array([0.5, 0.85, 0.8, 1.0, 0.82, 0.92, 0.85, 0.45, 0.2, 0.05, 0.0])

    wavelengths = np.linspace(400, 1000, NUM_PIXELS)
    brushes = []
    
    # Interpolate sensitivity across all our pixels
    interpolated_sensitivity = np.interp(wavelengths, sensitivity_wl, sensitivity_val)

    for i, wl in enumerate(wavelengths):
        base_rgb = wavelength_to_rgb(wl)
        sensitivity = interpolated_sensitivity[i]
        
        # Modulate brightness by sensitivity
        final_rgb = [int(c * sensitivity) for c in base_rgb]
        
        brushes.append(pg.mkBrush(color=final_rgb))
        
    return brushes
# --- End of MAJOR NEW FEATURE ---

# ---------- Main window ----------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Multi-Sensor Spectrometer with Dynamic Layout (S10077)')
        self.setGeometry(100, 100, 1400, 800)

        self.ser = None
        self.serial_thread = None
        self.stop_event = threading.Event()
        self.comm = Communication()
        
        self.plot_widgets = {}
        self.bar_items = {}
        
        # --- NEW: Generate scientifically accurate brushes on startup ---
        self.spectral_brushes = generate_spectral_brushes()

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

        self.layout_combo = QComboBox()
        # --- NEW: Added "3 Sensors" option ---
        self.layout_combo.addItems(["1 Sensor", "2 Sensors", "3 Sensors", "4 Sensors"])
        top_control_layout.addWidget(QLabel("Layout:"))
        top_control_layout.addWidget(self.layout_combo)
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

    def connect_signals(self):
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.comm.spec_data_ready.connect(self.update_plot)
        self.layout_combo.currentTextChanged.connect(self.setup_plot_layout)

    def setup_plot_layout(self, layout_text: str):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget: widget.deleteLater()
        
        self.plot_widgets.clear()
        self.bar_items.clear()
        
        num_sensors = int(layout_text.split(' ')[0])
        rows, cols = 1, 1
        if num_sensors == 2:
            cols = 2
        # --- NEW: Logic for 3-sensor layout ---
        elif num_sensors == 3:
            rows, cols = 2, 2
        elif num_sensors == 4:
            rows, cols = 2, 2
        
        sensor_id = 0
        wavelengths = np.linspace(400, 1000, NUM_PIXELS)
        
        for r in range(rows):
            for c in range(cols):
                if sensor_id < num_sensors:
                    plot_widget = pg.PlotWidget()
                    plot_widget.setTitle(f"Sensor {sensor_id}", color='w', size='12pt')
                    
                    plot_widget.setLabel('bottom', 'Wavelength (nm)')
                    plot_widget.setLabel('left', 'Intensity (12-bit ADC)')
                    plot_widget.setYRange(0, 4095)
                    plot_widget.setXRange(wavelengths[0], wavelengths[-1])
                    plot_widget.showGrid(x=True, y=True, alpha=0.3)
                    
                    # --- NEW: Use the pre-generated spectral brushes ---
                    bar_item = pg.BarGraphItem(
                        x=wavelengths,
                        height=np.zeros(NUM_PIXELS),
                        width=(wavelengths[1] - wavelengths[0]) * 0.9,
                        brushes=self.spectral_brushes
                    )
                    plot_widget.addItem(bar_item)
                    
                    self.grid_layout.addWidget(plot_widget, r, c)
                    
                    self.plot_widgets[sensor_id] = plot_widget
                    self.bar_items[sensor_id] = bar_item
                    
                    sensor_id += 1

    def update_plot(self, sensor_id: int, data_array: np.ndarray):
        if sensor_id in self.bar_items:
            self.bar_items[sensor_id].setOpts(height=data_array)

    def refresh_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            if 'USB' in port.device or 'ACM' in port.device or 'COM' in port.device:
                self.port_combo.addItem(f"{port.device} - {port.description}")

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
            if self.serial_thread and self.serial_thread.is_alive(): self.serial_thread.join(timeout=1.0)
            if self.ser and self.ser.is_open: self.ser.close()
            self.ser = None
            self.connect_btn.setText("Connect")
            self.status_label.setText("Disconnected")

    def closeEvent(self, event):
        self.stop_event.set()
        if self.serial_thread and self.serial_thread.is_alive(): self.serial_thread.join(timeout=1.0)
        if self.ser and self.ser.is_open: self.ser.close()
        event.accept()

# ---------- Entrypoint ----------
if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())