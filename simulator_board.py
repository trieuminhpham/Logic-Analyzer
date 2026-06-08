import argparse
import socket
import struct
import time


DEFAULT_BIND_HOST = '0.0.0.0'
DEFAULT_CONTROL_PORT = 8081
DEFAULT_PC_HOST = '127.0.0.1'
DEFAULT_PC_DATA_PORT = 8080


def build_test_samples(depth):
    samples = []
    counters = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53]
    for index in range(depth):
        value = 0
        for channel, period in enumerate(counters):
            if (index // period) % 2:
                value |= 1 << channel
        samples.append(value)
    return samples


def encode_rle(samples):
    if not samples:
        return b''

    out = bytearray()
    current = samples[0]
    count = 0

    for value in samples:
        if value == current and count < 0xFFFF:
            count += 1
            continue

        out.extend(struct.pack('<I', (count << 16) | current))
        current = value
        count = 1

    out.extend(struct.pack('<I', (count << 16) | current))
    return bytes(out)


def send_capture(pc_host, pc_data_port, depth):
    payload = encode_rle(build_test_samples(depth))
    with socket.create_connection((pc_host, pc_data_port), timeout=5.0) as sock:
        for offset in range(0, len(payload), 4096):
            sock.sendall(payload[offset:offset + 4096])
            time.sleep(0.002)


def parse_args():
    parser = argparse.ArgumentParser(description='Ethernet logic analyzer board simulator.')
    parser.add_argument('--bind-host', default=DEFAULT_BIND_HOST)
    parser.add_argument('--control-port', type=int, default=DEFAULT_CONTROL_PORT)
    parser.add_argument('--pc-host', default=DEFAULT_PC_HOST)
    parser.add_argument('--pc-data-port', type=int, default=DEFAULT_PC_DATA_PORT)
    return parser.parse_args()


def main():
    args = parse_args()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.bind_host, args.control_port))
        server.listen()
        print(f'Simulator listening for RUN on {args.bind_host}:{args.control_port}')
        print(f'Waveform data will be sent to {args.pc_host}:{args.pc_data_port}')

        while True:
            conn, addr = server.accept()
            with conn:
                command = conn.recv(16)
                if len(command) != 16:
                    print(f'Ignored short command from {addr}: {len(command)} bytes')
                    continue

                divider, mask, pattern, depth = struct.unpack('<IIII', command)
                print(
                    f'RUN from {addr}: divider={divider}, depth={depth}, '
                    f'mask=0x{mask:04X}, pattern=0x{pattern:04X}'
                )
                send_capture(args.pc_host, args.pc_data_port, depth)
                print(f'Sent {depth} decoded samples')


if __name__ == '__main__':
    main()
