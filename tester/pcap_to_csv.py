# #!/usr/bin/env python3
# """
# PCAP to CSV Extractor
# Extracts per-packet features into a flat CSV for downstream ML or analysis pipelines.

# Usage:
#     python pcap_to_csv.py <input.pcap> <output.csv>

# Dependencies:
#     pip install scapy
# """

# import sys
# import csv
# import argparse
# from pathlib import Path

# try:
#     from scapy.all import rdpcap, IP, TCP, UDP
# except ImportError:
#     raise SystemExit("Error: scapy is required. Install it with: pip install scapy")


# def get_protocol_name(pkt):
#     if IP not in pkt:
#         return None
#     proto_num = pkt[IP].proto
#     mapping = {1: "ICMP", 6: "TCP", 17: "UDP", 47: "GRE", 50: "ESP", 51: "AH"}
#     return mapping.get(proto_num, f"PROTO_{proto_num}")


# def get_transport_port(pkt, kind="sport"):
#     """Extract TCP/UDP source or destination port if present."""
#     layer = TCP if TCP in pkt else (UDP if UDP in pkt else None)
#     if layer is None:
#         return ""
#     return getattr(pkt[layer], kind, "")


# def get_payload_length(pkt):
#     if IP not in pkt:
#         return ""
#     ip_hdr_len = pkt[IP].ihl * 4
#     total_len = pkt[IP].len
#     if TCP in pkt:
#         tcp_hdr_len = pkt[TCP].dataofs * 4
#         return max(0, total_len - ip_hdr_len - tcp_hdr_len)
#     elif UDP in pkt:
#         udp_hdr_len = 8
#         return max(0, total_len - ip_hdr_len - udp_hdr_len)
#     return max(0, total_len - ip_hdr_len)


# def pcap_to_csv(input_path: str, output_path: str):
#     input_path = Path(input_path)
#     output_path = Path(output_path)

#     if not input_path.exists():
#         raise SystemExit(f"Input file not found: {input_path}")

#     packets = rdpcap(str(input_path))

#     with open(output_path, "w", newline="") as f:
#         writer = csv.writer(f)
#         # Column 6 suggestion: transport source port (universal for TCP/UDP)
#         # Alternatives you can swap in: "dst_port", "payload_len", "tcp_flags"
#         writer.writerow(["time", "ip_source", "ip_destination", "size", "protocol", "src_port"])

#         for pkt in packets:
#             if IP not in pkt:
#                 continue

#             row = [
#                 float(pkt.time),          # epoch timestamp (relative to capture start if from sniffer)
#                 pkt[IP].src,              # IP source
#                 pkt[IP].dst,              # IP destination
#                 len(pkt),                 # frame size (bytes on wire)
#                 get_protocol_name(pkt),   # L4 protocol name
#                 get_transport_port(pkt, "sport"),  # Column 6: src_port
#             ]
#             writer.writerow(row)

#     print(f"Wrote {len(packets)} packets to {output_path}")


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(description="Extract packet features from PCAP to CSV")
#     parser.add_argument("input_pcap", help="Path to input .pcap or .pcapng file")
#     parser.add_argument("output_csv", help="Path to output .csv file")
#     args = parser.parse_args()
#     pcap_to_csv(args.input_pcap, args.output_csv)


#!/usr/bin/env python3
"""
PCAP to CSV Extractor (dpkt version)
Extracts per-packet features into a flat CSV for downstream ML or analysis pipelines.

Usage:
    python pcap_to_csv.py <input.pcap> <output.csv>

Dependencies:
    pip install dpkt
"""

import csv
import argparse
import socket
from pathlib import Path

try:
    import dpkt
except ImportError:
    raise SystemExit("Error: dpkt is required. Install it with: pip install dpkt")


PROTO_MAP = {
    1: "ICMP",
    6: "TCP",
    17: "UDP",
    47: "GRE",
    50: "ESP",
    51: "AH",
}


def inet_to_str(inet):
    """Convert inet object to IP string."""
    try:
        return socket.inet_ntop(socket.AF_INET, inet)
    except ValueError:
        return socket.inet_ntop(socket.AF_INET6, inet)


def get_protocol_name(proto_num):
    return PROTO_MAP.get(proto_num, f"PROTO_{proto_num}")


def get_ports(transport):
    """Extract source and destination ports if TCP/UDP."""
    if isinstance(transport, (dpkt.tcp.TCP, dpkt.udp.UDP)):
        return transport.sport, transport.dport
    return "", ""


def get_payload_length(ip, transport):
    """Calculate transport payload length."""
    try:
        if isinstance(transport, dpkt.tcp.TCP):
            return len(transport.data)

        elif isinstance(transport, dpkt.udp.UDP):
            return len(transport.data)

        return len(ip.data)

    except Exception:
        return ""


def open_pcap(path):
    """Open .pcap or .pcapng transparently."""
    with open(path, "rb") as f:
        magic = f.read(4)

    f = open(path, "rb")

    # PCAPNG magic number
    if magic == b"\x0a\x0d\x0d\x0a":
        return dpkt.pcapng.Reader(f), f

    return dpkt.pcap.Reader(f), f


def pcap_to_csv(input_path: str, output_path: str):
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    reader, fp = open_pcap(str(input_path))

    packet_count = 0

    with open(output_path, "w", newline="") as csv_file:

        writer = csv.writer(csv_file)

        writer.writerow([
            "time",
            "ip_source",
            "ip_destination",
            "size",
            "protocol",
            "src_port"
        ])

        first_timestamp = None

        for timestamp, buf in reader:

            try:
                eth = dpkt.ethernet.Ethernet(buf)

                # Only IPv4
                if not isinstance(eth.data, dpkt.ip.IP):
                    continue

                ip = eth.data

                # ---------------------------------
                # RELATIVE TIME (Wireshark style)
                # ---------------------------------
                if first_timestamp is None:
                    first_timestamp = timestamp

                relative_time = timestamp - first_timestamp

                protocol = get_protocol_name(ip.p)

                src_ip = inet_to_str(ip.src)
                dst_ip = inet_to_str(ip.dst)

                transport = ip.data

                src_port, dst_port = get_ports(transport)

                row = [
                    float(relative_time),   # relative timestamp
                    src_ip,
                    dst_ip,
                    len(buf),
                    protocol,
                    src_port
                ]

                writer.writerow(row)
                packet_count += 1

            except Exception:
                # Skip malformed packets
                continue

    fp.close()

    print(f"Wrote {packet_count} packets to {output_path}")


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="Extract packet features from PCAP to CSV"
    )

    parser.add_argument(
        "input_pcap",
        help="Path to input .pcap or .pcapng file"
    )

    parser.add_argument(
        "output_csv",
        help="Path to output .csv file"
    )

    args = parser.parse_args()

    pcap_to_csv(args.input_pcap, args.output_csv)