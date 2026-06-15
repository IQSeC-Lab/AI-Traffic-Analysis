from scapy.all import rdpcap
from collections import Counter

packets = rdpcap("./cstr-Spaetzle-v60-7b-p01.pcap")
skipped = Counter()

for pkt in packets:
    if pkt.haslayer("IP"):
        continue
    # Identify why it was skipped
    if pkt.haslayer("IPv6"):
        skipped["IPv6"] += 1
    elif pkt.haslayer("ARP"):
        skipped["ARP"] += 1
    else:
        # Show the topmost layer name
        skipped[pkt.lastlayer().name] += 1

print(f"Total PCAP packets: {len(packets)}")
print(f"Skipped breakdown: {dict(skipped)}")
print(f"CSV would contain: {len(packets) - sum(skipped.values())}")