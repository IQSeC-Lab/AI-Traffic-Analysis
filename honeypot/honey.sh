#!/usr/bin/env bash
set -euo pipefail

echo ".::       .::          .::      .::      .::       .::";
echo ".: .::   .:::          .::      .::      .: .::   .:::";
echo ".:: .:: . .::   .::    .::      .::      .:: .:: . .::";
echo ".::  .::  .:: .::  .:: .::      .::      .::  .::  .::";
echo ".::   .:  .::.::   .:: .::      .::      .::   .:  .::";
echo ".::       .::.::   .:: .::      .::      .::       .::";
echo ".::       .::  .:: .:::.::::::::.::::::::.::       .::";
echo "                                                      ";

echo "Adding fake AWS access tokens..."
mkdir -p ~/.aws
cat > ~/.aws/credentials <<EOF
[default]
aws_access_key_id=$(python3 -c "import secrets; print('AKIA' + ''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ234567') for _ in range(16)))")
aws_secret_access_key=$(python3 -c "import secrets,string; print(''.join(secrets.choice(string.ascii_letters + string.digits + '+/') for _ in range(40)))")
[profile]
aws_access_key_id=$(python3 -c "import secrets; print('ASIA' + ''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ234567') for _ in range(16)))")
aws_secret_access_key=$(python3 -c "import secrets,string; print(''.join(secrets.choice(string.ascii_letters + string.digits + '+/') for _ in range(40)))")
EOF

echo "Adding fake GitHub tokens..."
mkdir -p ~/.git-credentials.d  # Alternative spot
GITHUB_PAT=$(python3 -c "import secrets,string,random; print(random.choice(['ghp_','ghu_','gho_']) + ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(36)))")
echo "https://fakeuser:${GITHUB_PAT}@github.com" > ~/.git-credentials
echo "https://fakeuser:${GITHUB_PAT}@gitlab.com" >> ~/.git-credentials  # Multi-provider

echo "Adding fake DB passwords..."
mkdir -p ./fake_secrets
echo "DB_PASSWORD=$(python3 -c 'import secrets,string; print(\"\".join(secrets.choice(string.ascii_letters + string.digits + \"!@#$%^&*\") for _ in range(20)))')" > ./fake_secrets/db.env
echo "REDIS_PASS=$(python3 -c 'import secrets,string; print(\"\".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16)))')" >> ./fake_secrets/db.env

echo "Adding fake Crypto Wallet secrets..."
SEED=$(python3 -c "
import secrets
words = ['abandon', 'ability', 'able', 'about', 'above', 'absent', 'absorb', 'abstract']
print(' '.join(secrets.choice(words) for _ in range(12)))
")
echo "seed phrase: ${SEED}" > ./fake_secrets/wallet.txt
echo "private key: $(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> ./fake_secrets/wallet.txt
echo "wallet: 0x$(python3 -c 'import secrets; print(secrets.token_hex(20))')" >> ./fake_secrets/wallet.txt

# Bonus: Fake API keys
echo "OPENAI_API_KEY=sk-proj-fake1234567890abcdefghijklmnopqrstuvwxyz" > ./fake_secrets/api_keys.env

echo "Honeypot deployed! Monitor ~/.aws, ~/.git-credentials, ./fake_secrets, and /var/log/honeypot.log"
echo
echo "Monitoring: capturing network connections (tcpdump)..."
mkdir -p logs
sudo tcpdump -i any -w logs/net.pcap not host 127.0.0.1 &
TCPDUMP_PID=$!

# trap "kill $TCPDUMP_PID 2>/dev/null || true" EXIT
#
# MODEL="${1:-star23/baller13}"
#
# echo
# echo "Running malicious model..."
# echo "python load_model.py --model $MODEL"
# python load_model.py --model "$MODEL"
#
# echo
# echo "Waiting for a connection from the attacker..."
# sleep 600  # keep the environment up; adjust as needed

