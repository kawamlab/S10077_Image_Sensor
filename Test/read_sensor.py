import sys
import serial
import serial.tools.list_ports
import numpy as np
import threading

from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QLabel
from PySide6.QtCore import Signal, QObject
import pyqtgraph as pg

# ===== Configuration for S10077 Sensor =====
BAUD_RATE = 115200
NUM_PIXELS = 1024  # Updated for S10077
BEGIN_TOKEN = 'BEGIN,'
END_TOKEN = 'END'
SERIAL_ENCODING = 'utf-8'
READ_TIMEOUT_S = 0.1   # Serial readline() timeout for responsive shutdown

# ===== Qt signal bridge =====
class Communication(QObject):
    """Qt signals emitted from the serial reader thread."""
    spec_data_ready = Signal(np.ndarray)

# ---------- Parser ----------
def parse_spectrum_frame(line: str):
    """
    Parse the data frame from the STM32:
      "BEGIN,v0,v1,...,v1023,END\\r\\n"
    Returns a numpy array of length NUM_PIXELS or None if parsing fails.
    """
    line = line.strip()
    if not line.startswith(BEGIN_TOKEN) or not line.endswith(END_TOKEN):
        return None
    try:
        # Extract the comma-separated values between BEGIN, and ,END
        payload = line[len(BEGIN_TOKEN):-len(END_TOKEN)]
        # The STM32 code might leave a trailing comma, so rstrip it
        payload = payload.rstrip(',')
        
        if not payload:
            return None
        
        # Convert the string of numbers to a numpy array
        arr = np.fromstring(payload, sep=',', dtype=np.uint16)
        
        # Validate the number of pixels
        if arr.size != NUM_PIXELS:
            print(f"Warning: Received frame with {arr.size} pixels, expected {NUM_PIXELS}.")
            return None
            
        return arr
    except ValueError as e:
        print(f"Parsing error: {e}")
        return None

# ---------- Serial reader thread ----------
def serial_reader_thread(ser: serial.Serial, comm: Communication, stop_event: threading.Event):
    """
    Blocking reader loop that reads lines, parses them, and emits signals.
    Exits promptly when stop_event is set or the port is closed.
    """
    print("Serial reader thread started...")
    while not stop_event.is_set():
        if ser is None or not ser.is_open:
            break
        try:
            line_bytes = ser.readline()
            if not line_bytes:
                continue

            line = line_bytes.decode(SERIAL_ENCODING, errors='ignore')
            
            spectrum_data = parse_spectrum_frame(line)
            if spectrum_data is not None:
                comm.spec_data_ready.emit(spectrum_data)

        except serial.SerialException:
            print("[Serial error]")
            break
        except Exception as e:
            print(f"[Reader thread exception] {e}")
            break

    print("Serial reader thread exited.")

# ---------- Main window ----------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Hamamatsu S10077 Real-time Spectrometer (PySide6 / PyQtGraph)')
        self.setGeometry(100, 100, 1200, 600)

        # --- State ---
        self.ser = None
        self.serial_thread = None
        self.stop_event = threading.Event()
        self.comm = Communication()

        # --- UI ---
        self.init_ui()
        self.connect_signals()
        self.refresh_ports()

    def init_ui(self):
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        self.setCentralWidget(central_widget)

        # Control bar
        control_layout = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(250)
        self.refresh_btn = QPushButton("Refresh")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setCheckable(True)
        self.status_label = QLabel("Select a serial port and connect")

        control_layout.addWidget(QLabel("Serial Port:"))
        control_layout.addWidget(self.port_combo)
        control_layout.addWidget(self.refresh_btn)
        control_layout.addWidget(self.connect_btn)
        control_layout.addStretch()
        control_layout.addWidget(self.status_label)

        # Plot area
        self.plot_widget = pg.PlotWidget()
        main_layout.addLayout(control_layout)
        main_layout.addWidget(self.plot_widget)

        # Plot config
        self.wavelengths = np.linspace(400, 1000, NUM_PIXELS) # Wavelength range for S10077
        self.plot_widget.setLabel('bottom', 'Wavelength (nm)')
        self.plot_widget.setLabel('left', 'Intensity (12-bit ADC Value)')
        self.plot_widget.setYRange(0, 4095) # STM32 ADC is 12-bit
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)

        # Bar graph for spectrum display
        cmap = pg.colormap.get('viridis') # 'viridis' is good for scientific data
        brushes = [cmap.map(x) for x in np.linspace(0, 1, NUM_PIXELS)]
        self.bar_item = pg.BarGraphItem(
            x=self.wavelengths,
            height=np.zeros(NUM_PIXELS),
            width=(self.wavelengths[1] - self.wavelengths[0]) * 0.9, # Make bars slightly thinner
            brushes=brushes
        )
        self.plot_widget.addItem(self.bar_item)
        self.plot_widget.setXRange(self.wavelengths[0], self.wavelengths[-1])


    def connect_signals(self):
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.comm.spec_data_ready.connect(self.update_plot)

    def refresh_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            # Simple filter for common serial port names
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
                self.serial_thread = threading.Thread(
                    target=serial_reader_thread,
                    args=(self.ser, self.comm, self.stop_event)
                )
                self.serial_thread.start()

                self.connect_btn.setText("Disconnect")
                self.status_label.setText(f"Connected to {port_device}")
            except Exception as e:
                self.status_label.setText(f"Connection failed: {e}")
                self.connect_btn.setChecked(False)
        else:
            # Safe shutdown sequence
            self.stop_event.set()
            if self.serial_thread and self.serial_thread.is_alive():
                self.serial_thread.join(timeout=1.0)
            
            if self.ser and self.ser.is_open:
                self.ser.close()
            
            self.ser = None
            self.connect_btn.setText("Connect")
            self.status_label.setText("Disconnected")

    def update_plot(self, data_array: np.ndarray):
        """Update the bar graph with the latest spectrum data."""
        self.bar_item.setOpts(height=data_array)

    def closeEvent(self, event):
        """Ensure the serial thread is properly closed when the window is shut."""
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