#!/usr/bin/env python3

import subprocess

REPEATS = 10
net_delay= 500
net_jitter = 50
# for prompt_id in range(1,31):  # 33..50 inclusive
for prompt_id in range(1,11):  

    print("=" * 40)
    print(f"Running Prompt {prompt_id}")
    print(f"Repeats: {REPEATS}")
    print("=" * 40)

    subprocess.run(
        [
            "python",
            "main.py",
            "--net-delay", str(net_delay),
            "--net-jitter", str(net_jitter),
            "-p", str(prompt_id),
            "-r", str(REPEATS)
        ],
        check=True
    )

    print(f"Finished Prompt {prompt_id}")

print("All experiments completed.")