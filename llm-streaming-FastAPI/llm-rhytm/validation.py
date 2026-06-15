import os

def count_unique_p01(directory):
    unique_names = set()

    for filename in os.listdir(directory):
        if filename.endswith("-p01.pcap"):
            # remove the suffix "-p01.pcap"
            base_name = filename[:-len("-p02.pcap")]
            unique_names.add(base_name)

    print(f"Unique count: {len(unique_names)}")
    return unique_names


if __name__ == "__main__":
    dir_path = "captures/"  # change this to your directory
    uniques = count_unique_p01(dir_path)

    # optional: print them
    for name in sorted(uniques):
        print(name)