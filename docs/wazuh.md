# Wazuh

Wazuh is the SIEM that watches the lab. It's optional: the dashboard and worlds run fine without it.

It has three parts, all in Docker:

- **Wazuh's own stack** (manager, indexer, dashboard), from Wazuh's official `wazuh-docker` repo. You run it next to this repo, not inside it.
- **This repo's rules and decoders** (`wazuh/`), copied into the manager. They teach Wazuh what Minecraft and dashboard log lines mean.
- **An agent** that reads the lab's log files (each world's server log and the dashboard's audit log) and sends them to the manager.

This page sets all three up. For the list of rules and how to fire each one, see [wazuh/README.md](../wazuh/README.md).

Wazuh needs about 4 GB of RAM on top of your worlds.

## 1. Start Wazuh's stack

Clone `wazuh-docker` **next to** this repo (not inside it), at the version this repo was tested with:

```sh
git clone https://github.com/wazuh/wazuh-docker.git -b v4.9.2
cd wazuh-docker/single-node
```

**Keep it on your PC only.** By default it listens on every network interface. Open `docker-compose.yml` in `single-node/` and put `127.0.0.1:` in front of each published port, for example `"443:5601"` becomes `"127.0.0.1:443:5601"`. The agent reaches the manager over Docker's own network, so nothing breaks.

**Linux only:** the indexer needs a kernel setting, or it won't start:

```sh
sudo sysctl -w vm.max_map_count=262144
echo "vm.max_map_count=262144" | sudo tee /etc/sysctl.d/99-wazuh.conf   # keep it after reboots
```

Generate its certificates (once), then start it:

```sh
docker compose -f generate-indexer-certs.yml run --rm generator
docker compose up -d
```

The first start takes a few minutes. Open **https://localhost**, accept the self-signed certificate warning, and log in with `admin` / `SecretPassword`. That's Wazuh's public default, so [change it](https://documentation.wazuh.com/4.9/deployment-options/docker/wazuh-container.html) if anything else can reach this PC.

The page says **"Wazuh dashboard server is not ready yet"** until the indexer behind it is up. A minute or two is normal. If it stays that way, see [Troubleshooting](#troubleshooting).

## 2. Load this repo's rules

From **this repo's** folder (on Windows, in PowerShell or after `export MSYS_NO_PATHCONV=1` in Git Bash):

```sh
docker cp wazuh/decoders/minecraft_decoders.xml single-node-wazuh.manager-1:/var/ossec/etc/decoders/
docker cp wazuh/rules/mc_dashboard_rules.xml single-node-wazuh.manager-1:/var/ossec/etc/rules/
docker cp wazuh/rules/minecraft_rules.xml single-node-wazuh.manager-1:/var/ossec/etc/rules/
docker exec single-node-wazuh.manager-1 chown wazuh:wazuh /var/ossec/etc/decoders/minecraft_decoders.xml /var/ossec/etc/rules/mc_dashboard_rules.xml /var/ossec/etc/rules/minecraft_rules.xml
docker exec single-node-wazuh.manager-1 /var/ossec/bin/wazuh-control restart
```

`single-node-wazuh.manager-1` is the manager's default container name; check yours with `docker ps`. The files are kept across restarts. Repeat this step when you pull rule changes.

## 3. Run the agent

The simplest way, on Windows and Linux alike, is the agent container in `wazuh/agent/docker/`. It already knows which log files to read. From this repo's folder:

```sh
docker build -t mc-lab-wazuh-agent -f wazuh/agent/docker/Dockerfile wazuh/agent
docker run -d --name mc-lab-wazuh-agent --hostname mc-lab-box --restart unless-stopped --network single-node_default -v "${PWD}/logs:/opt/minecraft-siem-lab/logs:ro" -v "${PWD}/worlds:/opt/minecraft-siem-lab/worlds:ro" mc-lab-wazuh-agent
```

It registers with the manager on its first start and shows up in Wazuh as **mc-lab-box** under *Agents*. Wazuh's network has to exist first, so start the stack (step 1) before the agent.

On Linux you can install the agent directly on the host instead; see [wazuh/README.md](../wazuh/README.md#install-on-the-agent).

## 4. See alerts

Make something happen: enter a wrong password on the dashboard login a few times, or stop and start a world. Then in Wazuh open **Threat Hunting** (or *Security events*) and search `rule.id:1001*` for dashboard alerts or `rule.id:1002*` for game server alerts. Every alert about a world has `data.world` set to its name.

[wazuh/README.md](../wazuh/README.md#triggering-the-rules-for-real-for-screenshots) lists how to trigger each rule.

## After a reboot

Docker has to be running first (start Docker Desktop on Windows). Then:

```sh
cd wazuh-docker/single-node
docker compose up -d
```

The agent container restarts by itself once Docker is up, and reconnects when the manager is back. Give the Wazuh dashboard a couple of minutes before opening https://localhost.

## Troubleshooting

**"Wazuh dashboard server is not ready yet" for more than five minutes.** The Wazuh dashboard can't reach the indexer. Look at the indexer's log first:

```sh
docker logs --tail 50 single-node-wazuh.indexer-1
docker logs --tail 50 single-node-wazuh.dashboard-1
```

- `max virtual memory areas vm.max_map_count [65530] is too low` (Linux): run the `sysctl` commands from step 1, then `docker compose up -d`.
- The indexer exited or keeps restarting with out-of-memory errors: give Docker more memory (Docker Desktop: *Settings > Resources*, or `.wslconfig` with the WSL 2 backend) or stop a world.
- Certificate errors: the certificates from step 1 weren't generated, or were generated in a different folder. Run the generator again in `single-node/`, then `docker compose up -d`.
- If none of those show up, restart the stack in order: `docker compose down` then `docker compose up -d` (this keeps your data; it lives in Docker volumes).

**The agent doesn't show up, or shows as disconnected.** `docker logs mc-lab-wazuh-agent` shows why. It must be on the manager's network (`single-node_default`); if your stack folder has another name, the network is `<folder>_default`.

**Alerts about players have no world name.** The agent isn't reading through the paths in `wazuh/agent/localfile.conf`. The repo's `logs/` and `worlds/` folders must be mounted at `/opt/minecraft-siem-lab/` as in step 3.
