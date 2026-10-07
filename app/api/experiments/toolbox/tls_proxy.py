#!/usr/bin/env python3
"""
TLS-terminating proxy in front of Ollama, from marble-traffic-dataset's
scripts/tls_ollama_proxy.py. It runs in the Ollama container's network namespace
(see marble_engine.py): the agents reach it over the run's network on --listen-port,
and it forwards plaintext to Ollama on that namespace's loopback. So the only traffic
on the captured interface is TLS, and no prompt or completion is on the wire.

The original listens on 127.0.0.1 because its agents run on the same host; here they
are in another container, so the address is an option (--listen-host).
"""

from __future__ import annotations

import argparse
import socket
import ssl
import threading


def relay(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle_client(tls_conn: ssl.SSLSocket, upstream_host: str, upstream_port: int) -> None:
    try:
        upstream = socket.create_connection((upstream_host, upstream_port), timeout=120)
    except OSError:
        tls_conn.close()
        return
    t1 = threading.Thread(target=relay, args=(tls_conn, upstream), daemon=True)
    t2 = threading.Thread(target=relay, args=(upstream, tls_conn), daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    tls_conn.close()
    upstream.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=11443)
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--upstream-port", type=int, default=11434)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args()

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=args.cert, keyfile=args.key)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((args.listen_host, args.listen_port))
    listener.listen(64)
    print(f"TLS proxy listening on {args.listen_host}:{args.listen_port} -> {args.upstream_host}:{args.upstream_port}",
          flush=True)

    while True:
        raw_conn, addr = listener.accept()
        try:
            tls_conn = context.wrap_socket(raw_conn, server_side=True)
        except (ssl.SSLError, OSError) as e:
            print(f"TLS handshake failed from {addr}: {e}", flush=True)
            raw_conn.close()
            continue
        threading.Thread(target=handle_client, args=(tls_conn, args.upstream_host, args.upstream_port), daemon=True).start()


if __name__ == "__main__":
    main()
