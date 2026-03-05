# Attack Models

## Attack 1

`Alice` is testing some pytorch models she downloaded from huggin face/ or `reviewer` is testing some novel implementation of a paper and he was provided some `.pt` files

### Setup

To test use the following commands:

```
docker compose up -d --build
```

**Attacker**:

```
docker exec -it attacker bash
tcpdump -i any icmp -n
```

**Victim**:

```
docker exec -it victim bash
python validate.py
```
