#!/bin/bash

# =====================================================
# Process all PCAP files in a folder
# Usage:
#   ./process_pcaps.sh /path/to/pcap/folder
# =====================================================

# Check if folder argument was provided
if [ $# -ne 1 ]; then
    echo "Usage: $0 <pcap_folder>"
    exit 1
fi

PCAP_DIR="$1"

# Check if directory exists
if [ ! -d "$PCAP_DIR" ]; then
    echo "Error: Directory does not exist -> $PCAP_DIR"
    exit 1
fi

# Process every .pcap file
for pcap in "$PCAP_DIR"/*.pcap; do

    # Skip if no files found
    [ -e "$pcap" ] || continue

    # Remove .pcap extension
    base_name=$(basename "$pcap" .pcap)

    # Create output CSV path
    output_csv="$PCAP_DIR/${base_name}.csv"

    echo "[+] Processing: $pcap"
    echo "    Output: $output_csv"

    # Run Python script
    python pcap_to_csv.py "$pcap" "$output_csv"

done

echo "[+] Done processing all PCAP files."




# #!/bin/bash

# # =====================================================
# # Process all PCAP files — all packets, minimal fields
# # Usage: ./process_pcaps.sh /path/to/pcap/folder
# # =====================================================

# if [ $# -ne 1 ]; then
#     echo "Usage: $0 <pcap_folder>"
#     exit 1
# fi

# PCAP_DIR="$1"

# if [ ! -d "$PCAP_DIR" ]; then
#     echo "Error: Directory does not exist -> $PCAP_DIR"
#     exit 1
# fi

# for pcap in "$PCAP_DIR"/*.pcap; do
#     [ -e "$pcap" ] || continue

#     base_name=$(basename "$pcap" .pcap)
#     output_csv="$PCAP_DIR/${base_name}.csv"

#     echo "[+] Processing: $pcap"
#     echo "    Output: $output_csv"

#     tshark -r "$pcap" \
#     -T fields \
#     -e frame.number \
#     -e frame.time_relative \
#     -e frame.time_delta \
#     -e frame.len \
#     -e ip.src \
#     -e ip.dst \
#     -e ipv6.src \
#     -e ipv6.dst \
#     -e ip.proto \
#     -e _ws.col.Protocol \
#     -e icmp.type \
#     -e icmp.code \
#     -e dns.qry.name \
#     -E header=y \
#     -E separator=, \
#     -E quote=d \
#     -E occurrence=f \
#     > "$output_csv"
# done

# echo "[+] Done processing all PCAP files."