#!/usr/bin/env python3
"""Forward one TLS connection and corrupt the first server application record.

This is only a negative test helper. It does not terminate TLS or know the PSK;
it flips one ciphertext byte after the TLS record header, so the ESP32 must
reject the record's AEAD authentication and reconnect.
"""
import argparse
import socket
import threading


def recv_exact(sock, count):
    data = bytearray()
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            return None
        data.extend(chunk)
    return data


def relay(source, target, corrupt):
    flipped = False
    try:
        while True:
            header = recv_exact(source, 5)
            if header is None:
                break
            length = (header[3] << 8) | header[4]
            body = recv_exact(source, length)
            if body is None:
                break
            if corrupt and not flipped and header[0] == 23 and body:
                body[-1] ^= 0x01
                flipped = True
                print("Corrupted one TLS application-record byte", flush=True)
            target.sendall(header + body)
    finally:
        try:
            target.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=4568)
    parser.add_argument("--target", required=True, help="real secure_peer IPv4 address")
    parser.add_argument("--target-port", type=int, default=4567)
    args = parser.parse_args()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((args.listen, args.port))
    listener.listen(1)
    print(f"TLS corruption proxy listening on {args.listen}:{args.port}", flush=True)
    client, address = listener.accept()
    print(f"Accepted {address}; forwarding to {args.target}:{args.target_port}", flush=True)
    target = socket.create_connection((args.target, args.target_port), timeout=10)
    left = threading.Thread(target=relay, args=(client, target, False), daemon=True)
    right = threading.Thread(target=relay, args=(target, client, True), daemon=True)
    left.start()
    right.start()
    left.join()
    right.join()
    client.close()
    target.close()


if __name__ == "__main__":
    main()
