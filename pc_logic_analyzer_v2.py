import argparse
import sys
import socket
import struct
import numpy as np
import pyqtgraph as pg
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QLabel, QPushButton, QComboBox, QCheckBox, 
                             QGroupBox, QGridLayout, QLineEdit, QSpinBox)
from PyQt5.QtCore import QThread, pyqtSignal, Qt

DATA_LISTEN_HOST = '0.0.0.0'
DATA_LISTEN_PORT = 8080
CONTROL_PORT = 8081
DEFAULT_BOARD_IP = '192.168.1.10'
MAX_DISPLAY_SAMPLES = 250_000
RECV_CHUNK_BYTES = 65536


def decode_rle_packet(packet):
    """Decode uint32 RLE words: count[31:16] | value[15:0]."""
    words = np.frombuffer(packet, dtype='<u4')
    vals = words & 0xFFFF
    counts = (words >> 16) & 0xFFFF
    valid = counts > 0
    if not np.any(valid):
        return np.array([], dtype=np.uint16)
    return np.repeat(vals[valid], counts[valid]).astype(np.uint16, copy=False)


def build_run_command(divider, mask, pattern, depth):
    """Build the 16-byte little-endian control command sent to the board."""
    return struct.pack('<IIII', divider, mask, pattern, depth)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="PC waveform viewer for a 16-channel Ethernet logic analyzer."
    )
    parser.add_argument('--board-ip', default=DEFAULT_BOARD_IP, help='IP address of the FPGA/MCU board.')
    parser.add_argument('--data-host', default=DATA_LISTEN_HOST, help='Local host/IP for the PC data TCP server.')
    parser.add_argument('--data-port', type=int, default=DATA_LISTEN_PORT, help='Local TCP port that receives waveform data.')
    parser.add_argument('--control-port', type=int, default=CONTROL_PORT, help='Board TCP port that receives RUN commands.')
    parser.add_argument(
        '--max-display-samples',
        type=int,
        default=MAX_DISPLAY_SAMPLES,
        help='Maximum decoded samples kept in the plot buffer.',
    )
    return parser.parse_args(argv)

# =====================================================================
# LUỒNG 1: XỬ LÝ MẠNG (Nhận 16 Kênh TCP)
# =====================================================================
class TcpReceiverThread(QThread):
    data_received = pyqtSignal(np.ndarray)
    status_changed = pyqtSignal(str)

    def __init__(self, host=DATA_LISTEN_HOST, port=DATA_LISTEN_PORT):
        super().__init__()
        self.host = host
        self.port = port
        self._running = True

    def stop(self):
        self._running = False
        self.wait(1500)

    def run(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.port))
            s.listen()
            s.settimeout(0.5)
        except OSError as e:
            self.status_changed.emit(f"Không mở được data socket {self.host}:{self.port}: {e}")
            return

        with s:
            self.status_changed.emit(f"Đang lắng nghe dữ liệu tại {self.host}:{self.port}")

            while self._running:
                try:
                    conn, addr = s.accept()
                except socket.timeout:
                    continue

                with conn:
                    conn.settimeout(0.5)
                    pending = b''
                    self.status_changed.emit(f"Board đã kết nối dữ liệu từ {addr[0]}:{addr[1]}")

                    while self._running:
                        try:
                            raw_data = conn.recv(RECV_CHUNK_BYTES)
                            if not raw_data:
                                break
                        except socket.timeout:
                            continue
                        except Exception as e:
                            self.status_changed.emit(f"Lỗi mạng: {e}")
                            break

                        pending += raw_data
                        usable_len = len(pending) - (len(pending) % 4)
                        if usable_len == 0:
                            continue

                        packet = pending[:usable_len]
                        pending = pending[usable_len:]

                        try:
                            flat_array = decode_rle_packet(packet)
                            if len(flat_array) > 0:
                                self.data_received.emit(flat_array)
                        except Exception as e:
                            self.status_changed.emit(f"Lỗi parse dữ liệu: {e}")
                            break

                    self.status_changed.emit("Mất kết nối dữ liệu, đang chờ board kết nối lại")

# =====================================================================
# LUỒNG 2: GIAO DIỆN (Logic Analyzer 16 Kênh)
# =====================================================================
class LogicAnalyzerGUI(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.setWindowTitle("Zynq Logic Analyzer Pro - 16 Channels")
        self.resize(1300, 800)
        self.capture_buffer = np.array([], dtype=np.uint16)
        self.data_host = config.data_host
        self.max_display_samples = config.max_display_samples
        self.tcp_thread = None

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # ---------------------------------------------------------
        # PANEL BÊN TRÁI: ĐIỀU KHIỂN (CONTROL PANEL)
        # ---------------------------------------------------------
        control_panel = QWidget()
        control_panel.setFixedWidth(320)
        control_layout = QVBoxLayout(control_panel)
        main_layout.addWidget(control_panel)

        # 1. Ethernet
        group_net = QGroupBox("1. Ethernet")
        layout_net = QGridLayout()
        self.board_ip_edit = QLineEdit(config.board_ip)
        self.control_port_spin = QSpinBox()
        self.control_port_spin.setRange(1, 65535)
        self.control_port_spin.setValue(config.control_port)
        self.data_port_spin = QSpinBox()
        self.data_port_spin.setRange(1, 65535)
        self.data_port_spin.setValue(config.data_port)
        self.btn_restart_receiver = QPushButton("Mở lại data port")
        self.btn_restart_receiver.clicked.connect(self.start_data_receiver)
        layout_net.addWidget(QLabel("Board IP"), 0, 0)
        layout_net.addWidget(self.board_ip_edit, 0, 1)
        layout_net.addWidget(QLabel("Control port"), 1, 0)
        layout_net.addWidget(self.control_port_spin, 1, 1)
        layout_net.addWidget(QLabel("Data port"), 2, 0)
        layout_net.addWidget(self.data_port_spin, 2, 1)
        layout_net.addWidget(self.btn_restart_receiver, 3, 0, 1, 2)
        group_net.setLayout(layout_net)
        control_layout.addWidget(group_net)

        # 2. Tần số lấy mẫu
        group_clock = QGroupBox("2. Tần số lấy mẫu")
        layout_clock = QVBoxLayout()
        self.combo_samplerate = QComboBox()
        # Lưu trữ cặp dữ liệu: (Tên hiển thị, (Hệ số chia Divider, Tần số Hz))
        # Giả định Clock gốc của IDDR là 400 MSPS (400,000,000 Hz)
        self.combo_samplerate.addItem("400 MSPS", (1, 400_000_000))
        self.combo_samplerate.addItem("100 MSPS", (4, 100_000_000))
        self.combo_samplerate.addItem("10 MSPS", (40, 10_000_000))
        self.combo_samplerate.addItem("1 MSPS", (400, 1_000_000))
        self.combo_samplerate.addItem("100 KSPS", (4000, 100_000))
        # Cập nhật kết quả đo lường nếu đổi tần số
        self.combo_samplerate.currentIndexChanged.connect(self.update_measurements)
        layout_clock.addWidget(self.combo_samplerate)
        group_clock.setLayout(layout_clock)
        control_layout.addWidget(group_clock)

        # 3. Trigger (16 Kênh chia 2 cột)
        group_trigger = QGroupBox("3. Điều kiện Trigger")
        layout_trigger = QGridLayout()
        layout_trigger.addWidget(QLabel("CH"), 0, 0); layout_trigger.addWidget(QLabel("Msk"), 0, 1); layout_trigger.addWidget(QLabel("Pat"), 0, 2)
        layout_trigger.addWidget(QLabel("CH"), 0, 4); layout_trigger.addWidget(QLabel("Msk"), 0, 5); layout_trigger.addWidget(QLabel("Pat"), 0, 6)
        layout_trigger.setColumnMinimumWidth(3, 15) 

        self.mask_cbs = []
        self.pattern_cbs = []
        
        # Duyệt 16 kênh
        for i in range(15, -1, -1):
            row = 15 - i + 1 if i >= 8 else 7 - i + 1
            col = 0 if i >= 8 else 4
                
            layout_trigger.addWidget(QLabel(f"CH{i}"), row, col)
            
            cb_mask = QCheckBox()
            layout_trigger.addWidget(cb_mask, row, col + 1)
            
            cb_pattern = QCheckBox("1")
            cb_pattern.setEnabled(False)
            cb_mask.toggled.connect(cb_pattern.setEnabled)
            layout_trigger.addWidget(cb_pattern, row, col + 2)

            self.mask_cbs.append(cb_mask)
            self.pattern_cbs.append(cb_pattern)

        group_trigger.setLayout(layout_trigger)
        control_layout.addWidget(group_trigger)

        # 4. Độ sâu lấy mẫu
        group_depth = QGroupBox("4. Số lượng mẫu (Depth)")
        layout_depth = QVBoxLayout()
        self.combo_depth = QComboBox()
        self.combo_depth.addItem("1024 Samples", 1024)
        self.combo_depth.addItem("4096 Samples", 4096)
        self.combo_depth.addItem("16384 Samples", 16384)
        self.combo_depth.addItem("65536 Samples", 65536)
        self.combo_depth.addItem("262144 Samples", 262144)
        layout_depth.addWidget(self.combo_depth)
        group_depth.setLayout(layout_depth)
        control_layout.addWidget(group_depth)

        # 5. Nút bấm RUN
        self.btn_run = QPushButton(" BẮT ĐẦU (RUN) ")
        self.btn_run.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold; height: 40px; font-size: 14px;")
        self.btn_run.clicked.connect(self.start_capture)
        control_layout.addWidget(self.btn_run)
        control_layout.addStretch()

        # ---------------------------------------------------------
        # PANEL BÊN PHẢI: ĐỒ THỊ & PHÂN TÍCH (WAVEFORM VIEWER)
        # ---------------------------------------------------------
        plot_panel = QWidget()
        plot_layout = QVBoxLayout(plot_panel)
        main_layout.addWidget(plot_panel, stretch=1)

        self.status_label = QLabel("Đang khởi động TCP receiver...")
        self.status_label.setStyleSheet("background-color: #20242a; color: #e6edf3; font-family: monospace; padding: 8px;")
        plot_layout.addWidget(self.status_label)

        # Bảng hiển thị thông số đo lường (Measurement Display)
        self.measure_label = QLabel("Chưa có dữ liệu. Kéo 2 thanh dọc để đo lường.")
        self.measure_label.setStyleSheet("background-color: #333; color: #00FF00; font-family: monospace; font-size: 16px; padding: 10px; border-radius: 5px;")
        plot_layout.addWidget(self.measure_label)

        # Cấu hình Màn hình Vẽ (PyQtGraph)
        self.plot_widget = pg.PlotWidget(background='#111') # Đen xám cực ngầu
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel('bottom', 'Thời gian / Samples')
        
        # Đổi tên trục Y thành tên Kênh
        yticks = [(i * 1.5 + 0.5, f"CH{i}") for i in range(16)]
        self.plot_widget.getAxis('left').setTicks([yticks])
        plot_layout.addWidget(self.plot_widget)

        # Khởi tạo 16 đường line với 16 màu khác biệt
        self.curves = []
        colors = ['#FF3333', '#33FF33', '#3333FF', '#FFFF33', '#FF33FF', '#33FFFF', 
                  '#FF9933', '#9933FF', '#3399FF', '#FF66B2', '#B2FF66', '#66B2FF', 
                  '#FFCC99', '#99FFCC', '#CC99FF', '#FFFFFF']
        for i in range(16):
            # width=1.5 giúp đường mảnh và sắc nét, stepMode="right" để tạo sóng vuông
            curve = self.plot_widget.plot(pen=pg.mkPen(colors[i], width=1.5), stepMode="right")
            self.curves.append(curve)

        # === TÍNH NĂNG CON TRỞ ĐO LƯỜNG (CURSORS) ===
        # Khởi tạo 2 thanh dọc (InfiniteLine) cho phép kéo thả
        self.cursor_a = pg.InfiniteLine(pos=10, angle=90, movable=True, pen=pg.mkPen('y', width=2, style=Qt.DashLine))
        self.cursor_b = pg.InfiniteLine(pos=50, angle=90, movable=True, pen=pg.mkPen('c', width=2, style=Qt.DashLine))
        self.plot_widget.addItem(self.cursor_a)
        self.plot_widget.addItem(self.cursor_b)
        
        # Bắt sự kiện khi chuột kéo thanh
        self.cursor_a.sigPositionChanged.connect(self.update_measurements)
        self.cursor_b.sigPositionChanged.connect(self.update_measurements)

        # Khởi động Luồng Mạng
        self.start_data_receiver()

    # ==========================================
    # CÁC HÀM XỬ LÝ LOGIC
    # ==========================================
    def start_capture(self):
        divider, _ = self.combo_samplerate.currentData()
        depth = self.combo_depth.currentData()
        board_ip = self.board_ip_edit.text().strip()
        control_port = self.control_port_spin.value()

        mask_val, pattern_val = 0, 0
        for i in range(16):
            bit_position = 15 - i
            if self.mask_cbs[i].isChecked():
                mask_val |= (1 << bit_position)
                if self.pattern_cbs[i].isChecked():
                    pattern_val |= (1 << bit_position)

        self.capture_buffer = np.array([], dtype=np.uint16)
        self.plot_widget.setXRange(0, depth, padding=0.02)
        payload = build_run_command(divider, mask_val, pattern_val, depth)

        try:
            with socket.create_connection((board_ip, control_port), timeout=2.0) as sock:
                sock.sendall(payload)
            self.status_label.setText(
                f"Đã gửi RUN tới {board_ip}:{control_port} | "
                f"divider={divider}, depth={depth}, mask=0x{mask_val:04X}, pattern=0x{pattern_val:04X}"
            )
        except OSError as e:
            self.status_label.setText(f"Không gửi được RUN tới {board_ip}:{control_port}: {e}")

    def update_plot(self, flat_data):
        if len(flat_data) == 0: return

        depth = min(self.combo_depth.currentData(), self.max_display_samples)
        if len(self.capture_buffer) == 0:
            self.capture_buffer = flat_data[-depth:]
        else:
            self.capture_buffer = np.concatenate((self.capture_buffer, flat_data))[-depth:]

        data = self.capture_buffer
        time_axis = np.arange(len(data) + 1)
        
        for i in range(16):
            ch_data = (data & (1 << i)) >> i
            ch_data_padded = np.append(ch_data, ch_data[-1])
            self.curves[i].setData(time_axis, ch_data_padded + (i * 1.5))

        self.plot_widget.setYRange(-0.2, 16 * 1.5, padding=0.02)
        self.plot_widget.setXRange(0, max(len(data), 1), padding=0.02)
        self.status_label.setText(f"Đã nhận {len(data)} mẫu đang hiển thị / depth {self.combo_depth.currentData()}")

    def start_data_receiver(self):
        if self.tcp_thread is not None:
            self.tcp_thread.stop()
            self.tcp_thread = None

        data_port = self.data_port_spin.value()
        self.status_label.setText(f"Đang mở data socket {self.data_host}:{data_port}...")
        self.tcp_thread = TcpReceiverThread(self.data_host, data_port)
        self.tcp_thread.data_received.connect(self.update_plot)
        self.tcp_thread.status_changed.connect(self.status_label.setText)
        self.tcp_thread.start()

    def update_measurements(self):
        # 1. Lấy vị trí của 2 con trỏ (số lượng sample)
        pos_a = self.cursor_a.value()
        pos_b = self.cursor_b.value()
        delta_samples = abs(pos_a - pos_b)

        # 2. Lấy Tần số lấy mẫu hiện tại (Hz) từ giao diện
        _, freq_hz = self.combo_samplerate.currentData()
        
        # 3. Tính toán Thời gian (Delta T) = Số sample / Tần số lấy mẫu
        delta_time_sec = delta_samples / freq_hz
        
        # Chuyển đổi đơn vị cho đẹp (us, ns, ms)
        if delta_time_sec < 1e-6:
            dt_str = f"{delta_time_sec * 1e9:.2f} ns"
        elif delta_time_sec < 1e-3:
            dt_str = f"{delta_time_sec * 1e6:.2f} µs"
        else:
            dt_str = f"{delta_time_sec * 1e3:.2f} ms"

        # 4. Tính toán Tần số của tín hiệu (1 / Delta T)
        # Cảnh báo chia cho 0 nếu 2 vạch trùng nhau
        if delta_time_sec > 0:
            signal_freq = 1 / delta_time_sec
            if signal_freq >= 1e6:
                freq_str = f"{signal_freq / 1e6:.2f} MHz"
            elif signal_freq >= 1e3:
                freq_str = f"{signal_freq / 1e3:.2f} kHz"
            else:
                freq_str = f"{signal_freq:.2f} Hz"
        else:
            freq_str = "N/A"

        # Hiển thị lên màn hình
        self.measure_label.setText(f"| Cursor A: {int(pos_a)} | Cursor B: {int(pos_b)} | ΔT: {dt_str} | Tần số: {freq_str} |")

    def closeEvent(self, event):
        if self.tcp_thread is not None:
            self.tcp_thread.stop()
        event.accept()

if __name__ == '__main__':
    args = parse_args(sys.argv[1:])
    QApplication.setAttribute(pg.QtCore.Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    window = LogicAnalyzerGUI(args)
    window.show()
    sys.exit(app.exec_())
