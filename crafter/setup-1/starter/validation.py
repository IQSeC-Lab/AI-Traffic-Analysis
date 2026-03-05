import torch

# Simulate "validation" / inference load
state_dict = torch.load('malicious_mnist.pt', weights_only=False)  # Triggers ping! [web:46]
print("Model loaded successfully – check tcpdump for ping.")
