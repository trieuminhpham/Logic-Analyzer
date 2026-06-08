# PC Logic Analyzer 16 Kenh Qua Ethernet

Ung dung nay hien thi song logic analyzer 16 kenh tren PC. Board/FPGA gui du lieu waveform qua Ethernet TCP, PC ve song bang PyQt5 va pyqtgraph.

## Tinh nang

- Hien thi 16 kenh logic tren cung mot waveform viewer.
- Nhan du lieu qua TCP data port.
- Gui lenh RUN/config qua TCP control port.
- Trigger mask/pattern cho tung kenh.
- Chon sample rate va depth.
- 2 cursor do thoi gian va tan so.
- Co board simulator de test khong can phan cung that.

## Cau truc du an

```text
.
├── pc_logic_analyzer_v2.py   # App GUI chinh tren PC
├── simulator_board.py        # Board gia lap de test app
├── requirements.txt          # Thu vien Python can cai
├── README.md                 # Huong dan su dung
└── .gitignore
```

Thu muc `logic_analyzer/` neu co la virtual environment local, khong can copy sang may khac.

## Yeu cau

- Python 3.10 tro len.
- He dieu hanh: Linux, Windows, macOS.
- Mang Ethernet noi duoc PC voi board.
- Board phai implement dung protocol o phan "Protocol Ethernet".

## Cai dat tren may moi

### Linux/macOS

```bash
cd "Logic Analyzer"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Chay app:

```bash
python pc_logic_analyzer_v2.py
```

### Windows PowerShell

```powershell
cd "Logic Analyzer"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Chay app:

```powershell
python pc_logic_analyzer_v2.py
```

Neu PowerShell chan activate script, chay:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

roi activate lai virtual environment.

## Chay bang virtualenv hien tai cua du an nay

May hien tai dang co virtualenv `logic_analyzer/`. Co the chay truc tiep:

```bash
logic_analyzer/bin/python pc_logic_analyzer_v2.py
```

Tren may khac nen tao `.venv` moi bang `requirements.txt`, khong nen copy thu muc `logic_analyzer/`.

## Cach su dung voi board that

1. Noi PC va board cung mang Ethernet.
2. Dat IP cho PC va board cung subnet.
   - Vi du PC: `192.168.1.100`
   - Vi du board: `192.168.1.10`
3. Mo app:

   ```bash
   python pc_logic_analyzer_v2.py --board-ip 192.168.1.10
   ```

4. Trong app:
   - `Board IP`: IP cua board.
   - `Control port`: port board lang nghe lenh RUN, mac dinh `8081`.
   - `Data port`: port PC lang nghe waveform, mac dinh `8080`.
   - `Sample rate`: tan so lay mau.
   - `Trigger`: tick `Msk` de chon kenh tham gia trigger, tick `Pat` de yeu cau muc logic 1.
   - `Depth`: so mau can capture.
5. Nhan `BAT DAU (RUN)`.
6. Board nhan lenh RUN, capture, roi connect ve PC data port de gui waveform.

Neu doi `Data port` trong app, nhan `Mo lai data port` de restart TCP receiver.

## Chay voi board simulator

Dung cach nay de test GUI tren bat ky may nao, khong can phan cung.

Mo terminal 1, chay app:

```bash
python pc_logic_analyzer_v2.py --board-ip 127.0.0.1
```

Mo terminal 2, chay simulator:

```bash
python simulator_board.py --pc-host 127.0.0.1
```

Quay lai app, nhan `BAT DAU (RUN)`. Simulator se nhan lenh RUN va gui waveform gia lap 16 kenh ve app.

## Tham so dong lenh cua app

```bash
python pc_logic_analyzer_v2.py \
  --board-ip 192.168.1.10 \
  --data-host 0.0.0.0 \
  --data-port 8080 \
  --control-port 8081 \
  --max-display-samples 250000
```

Y nghia:

- `--board-ip`: IP cua board that hoac simulator.
- `--data-host`: IP local PC bind TCP server nhan waveform. Thuong de `0.0.0.0`.
- `--data-port`: port PC nhan waveform.
- `--control-port`: port board nhan lenh RUN.
- `--max-display-samples`: gioi han so mau decoded giu trong plot de tranh GUI qua nang.

## Protocol Ethernet

Ung dung dung 2 ket noi TCP rieng:

### 1. Control connection: PC -> board

- Board mo TCP server tai `board_ip:control_port`.
- PC connect den board khi bam RUN.
- PC gui dung 16 byte:

```text
uint32 little-endian divider
uint32 little-endian trigger_mask
uint32 little-endian trigger_pattern
uint32 little-endian depth
```

Trong Python:

```python
struct.pack('<IIII', divider, trigger_mask, trigger_pattern, depth)
```

`trigger_mask` va `trigger_pattern` la bitmask 16 bit:

```text
bit 0  -> CH0
bit 1  -> CH1
...
bit 15 -> CH15
```

Neu bit trong `trigger_mask` bang 1, kenh do duoc dung de trigger. Gia tri mong muon nam trong `trigger_pattern`.

### 2. Data connection: board -> PC

- PC mo TCP server tai `data_host:data_port`, mac dinh `0.0.0.0:8080`.
- Board connect ve IP cua PC va port nay sau khi capture.
- Board gui stream cac word 32 bit little-endian.
- Moi word co dang:

```text
bits 31..16: count
bits 15..0 : value
```

`value` la trang thai 16 kenh tai thoi diem do:

```text
bit 0  -> CH0
bit 1  -> CH1
...
bit 15 -> CH15
```

`count` la so lan lap lai lien tiep cua `value`. Vi du:

```text
count = 5
value = 0x0003
```

nghia la 5 mau lien tiep co CH0=1, CH1=1, cac kenh con lai theo bit tuong ung.

## Luu y ve mang

- Neu app bao khong mo duoc data socket, co the port dang bi chuong trinh khac dung. Doi `Data port` roi nhan `Mo lai data port`.
- Firewall tren Windows/Linux co the chan board connect ve PC. Can allow Python/private network.
- Board va PC phai cung subnet hoac route duoc den nhau.
- Neu PC co nhieu card mang, lay dung IP Ethernet de board connect ve PC.

## Kiem tra nhanh

Kiem tra cu phap:

```bash
python -m py_compile pc_logic_analyzer_v2.py simulator_board.py
```

Kiem tra dependency:

```bash
python - <<'PY'
import numpy, PyQt5, pyqtgraph
print('OK')
PY
```

## Huong phat trien tiep

- Luu/copy waveform ra CSV/VCD.
- Them decode UART/SPI/I2C.
- Them zoom/pan toolbar va nut clear waveform.
- Tach thanh cac module `network.py`, `protocol.py`, `gui.py` khi code lon hon.
- Them config file JSON de luu IP/port/sample rate lan chay truoc.
