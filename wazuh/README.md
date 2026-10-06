# Wazuh detection for the Minecraft server and dashboard

Custom Wazuh decoders and rules for two log sources on the server box:

| Source | File | Format | Decoder |
|---|---|---|---|
| Dashboard audit log | `logs/audit.jsonl` | JSON lines | Wazuh's built-in `json` decoder |
| Minecraft server logs, one per world | `worlds/<world>/data/logs/latest.log` | Plain text | `decoders/minecraft_decoders.xml` |

```
wazuh/
├── agent/localfile.conf            # what the agent reads (goes in the agent's ossec.conf)
├── decoders/minecraft_decoders.xml # parses Minecraft log lines into fields
├── rules/mc_dashboard_rules.xml    # rules 100100-100199
├── rules/minecraft_rules.xml       # rules 100200-100299
├── samples/                        # example log lines, one file per source
└── test/run-logtest.sh             # replays samples through wazuh-logtest
```

## What it detects

**Dashboard (audit log)**

| Rule | Level | Fires when |
|---|---|---|
| 100101 | 3 | Successful login |
| 100102 | 5 | Failed login |
| 100103 | 10 | 5 failed logins within 2 minutes (brute force, MITRE T1110) |
| 100104 | 10 | The dashboard's own lockout trips |
| 100106 | 8 | Someone keeps trying a locked account |
| 100107 | 7 | A request is rejected for a missing or invalid CSRF token |
| 100105 | 3 | Logout |
| 100110 / 100111 / 100112 | 5 / 7 / 5 | World start / stop / restart from the dashboard |
| 100113 / 100114 | 3 / 8 | Backup created / backup failed |
| 100115 / 100116 | 7 | Whitelist add / remove |
| 100117 | 5 | World settings changed |
| 100118 | 7 | New world created (a new server container with its own game port) |
| 100119 | 10 | World deleted from the dashboard (container removed, folder moved to `worlds/.deleted/`) |
| 100120 | 12 | A login from an address that isn't the server box itself |

`login_invalid_form` events are decoded but don't alert (level 0).

Rule 100120 checks the localhost-only access model. The dashboard is
published on 127.0.0.1 only, so a login from another machine means the port
binding or the firewall changed and the dashboard is reachable from the
network. See the design notes for why Docker bridge addresses count as local.

**Minecraft server log**

| Rule | Level | Fires when |
|---|---|---|
| 100201 | 3 | Player connects (captures name and source IP) |
| 100202 / 100203 | 3 / 2 | Player joins / leaves |
| 100210 | 5 | Non-whitelisted player is refused |
| 100211 | 10 | 5 non-whitelisted attempts on one world within 5 minutes |
| 100212 | 5 | online-mode rejects a client that can't prove a Microsoft account |
| 100220 / 100221 / 100222 | 3 | Server starting / finished starting / shutting down |
| 100230 | 12 | Crash report written |
| 100231 | 12 | Watchdog kills a hung tick |
| 100232 | 10 | Unhandled exception in the server loop |
| 100233 | 3 | "Can't keep up" lag warning |
| 100234 | 12 | 3 starts of one world within 10 minutes (crash loop under a restart policy) |
| 100235 | 14 | 2 crash reports from one world within 15 minutes |
| 100240 / 100241 | 5 | Whitelist add / remove (actor `Rcon` = came from the dashboard) |
| 100242 / 100243 | 10 / 5 | Operator granted / removed |

Admin actions are logged from both sides on purpose: the dashboard records
who clicked the button, and the game log confirms the server actually
applied it.

## Install on the manager (Wazuh in Docker)

From the repo root on the server box, with the default single-node
wazuh-docker container name (check yours with `docker ps`):

```bash
MGR=single-node-wazuh.manager-1
docker cp wazuh/decoders/minecraft_decoders.xml $MGR:/var/ossec/etc/decoders/
docker cp wazuh/rules/mc_dashboard_rules.xml    $MGR:/var/ossec/etc/rules/
docker cp wazuh/rules/minecraft_rules.xml       $MGR:/var/ossec/etc/rules/
docker exec $MGR chown wazuh:wazuh \
  /var/ossec/etc/decoders/minecraft_decoders.xml \
  /var/ossec/etc/rules/mc_dashboard_rules.xml \
  /var/ossec/etc/rules/minecraft_rules.xml
docker exec $MGR /var/ossec/bin/wazuh-analysisd -t   # config check, no output means OK
docker exec $MGR /var/ossec/bin/wazuh-control restart
```

`/var/ossec/etc` is a named volume in wazuh-docker, so the files survive
container restarts.

## Install on the agent

The agent on the server box ships the two log files. Copy the blocks from
`agent/localfile.conf` into `/var/ossec/etc/ossec.conf` on that box, change
the `/opt/minecraft-siem-lab` prefix to where the repo is checked out, and restart the agent (`sudo systemctl restart wazuh-agent`).

## Test with wazuh-logtest

```bash
wazuh/test/run-logtest.sh single-node-wazuh.manager-1
```

Every sample line should show the rule it was written for; a line printed as
`NO RULE` means nothing matched. Output from Wazuh 4.9.2:

```
=== dashboard-audit.log ===
rule 100101  lvl 3   Minecraft dashboard: user david logged in
rule 100105  lvl 3   Minecraft dashboard: user david logged out
rule 100100  lvl 0   Minecraft dashboard: audit event
rule 100107  lvl 7   Minecraft dashboard: request rejected, missing or invalid CSRF token
rule 100102  lvl 5   Minecraft dashboard: failed login for user admin (unknown_user)
rule 100102  lvl 5   Minecraft dashboard: failed login for user admin (unknown_user)
rule 100102  lvl 5   Minecraft dashboard: failed login for user david (bad_password)
rule 100102  lvl 5   Minecraft dashboard: failed login for user david (bad_password)
rule 100103  lvl 10  Minecraft dashboard: possible brute force, 5 failed logins in 2 minutes
rule 100104  lvl 10  Minecraft dashboard: account david locked out after repeated failed logins
rule 100106  lvl 8   Minecraft dashboard: login attempt for locked account david
rule 100120  lvl 12  Minecraft dashboard: login attempt from non-localhost address 192.168.1.50, dashboard may be exposed
...
=== minecraft-server.log ===
rule 100210  lvl 5   Minecraft world survival: non-whitelisted player Griefer tried to join
rule 100211  lvl 10  Minecraft world survival: 5 non-whitelisted join attempts on one world in 5 minutes
rule 100242  lvl 10  Minecraft world survival: Rcon made Alex a server operator
rule 100230  lvl 12  Minecraft world survival: CRASHED, report at /data/./crash-reports/crash-2026-10-05_18.10.01-server.txt
rule 100235  lvl 14  Minecraft world survival: 2 crashes in 15 minutes, crash loop
rule 100234  lvl 12  Minecraft world survival: started 3 times in 10 minutes, possible crash loop
...
```

Beyond logtest, the agent side was checked once inside the same container:
the `localfile` blocks above, pointed at two world folders, produced alerts
with `data.world` set to the right world, 3 starts split across two worlds
did not fire the crash-loop rule, and 3 starts of one world did.

To check a single line by hand: `docker exec -it $MGR /var/ossec/bin/wazuh-logtest`
and paste it in.

## Triggering the rules for real (for screenshots)

wazuh-logtest proves the rules parse; these prove the whole pipeline
(agent → manager → dashboard alert):

| Rule | How to trigger it |
|---|---|
| 100103, 100104 | Enter a wrong password at http://localhost:5000/login five times |
| 100210, 100211 | Remove a friend from the whitelist and have them try to join 5 times (or use a second account) |
| 100111, 100115 | Stop a world / add someone to its whitelist from the dashboard |
| 100242 | `op <name>` through the dashboard console |
| 100230, 100235 | There is no safe way to crash the server on demand. Append a crash line to the live log instead, which still goes through the agent: `echo "[$(date +%T)] [Server thread/ERROR]: This crash report has been saved to: /data/crash-reports/test.txt" >> worlds/survival/data/logs/latest.log` (twice for 100235) |
| 100234 | Restart one world 3 times within 10 minutes |
| 100120 | Only fires if the dashboard is reachable off-box, which it shouldn't be. Test it with wazuh-logtest instead |

## Design notes

- **No custom decoder for the audit log.** Wazuh's built-in `json` decoder
  matches any line starting with `{` and is evaluated before custom decoders,
  so a custom JSON decoder would never run. The rules key on
  `"app": "mc-dashboard"` instead.
- **Audit log field names** come from `dashboard/mcdash/audit.py`: `app`,
  `event`, `user`, `src_ip`, plus `world`, `target`, `reason` and so on per
  event. If an event is renamed there, update the matching `<field>` in
  `rules/mc_dashboard_rules.xml` and `samples/dashboard-audit.log`.
- **Why Docker bridge addresses count as local.** The dashboard runs in a
  container, so a browser on the server box reaches Flask through Docker,
  and `src_ip` is the bridge gateway (something like 172.18.0.1), not
  127.0.0.1. Rule 100120 therefore treats 127.0.0.0/8, ::1 and
  172.16.0.0/12 as local. If the port were published on 0.0.0.0, a request
  from another machine would keep its real address through Docker's NAT and
  the rule would fire. The blind spot is a home LAN that itself uses
  172.16.0.0/12 addresses (most use 192.168.x.x).
- **Several worlds.** Each world is its own server with its own
  `latest.log`, and Minecraft's log lines don't name the world. The agent's
  `out_format` puts the file path in front of every line
  (`/opt/minecraft-siem-lab/worlds/survival/data/logs/latest.log: [18:00:00] ...`),
  the decoder pulls `world` out of that path, and the counting rules use
  `<same_field>world</same_field>` so two worlds' events never add up to one
  alert. A raw line pasted into wazuh-logtest without the prefix still
  decodes, but the alert reads "Minecraft world : ..." with no name.
- **Dashboard events** about a world carry their own `world` field, so
  dashboard and game alerts can be filtered by the same `data.world`.
- **Source IPs on the game server.** Players come in through playit.gg, so
  the server sees the tunnel's address, not the player's real IP. `srcip` on
  Minecraft alerts is therefore the tunnel endpoint, which is why the
  non-whitelisted rule counts attempts overall rather than per IP.
- **Both log styles.** The decoder accepts vanilla/Fabric headers
  (`[14:50:01] [Server thread/INFO]:`) and Paper/Spigot headers
  (`[14:50:01 INFO]:`), so it keeps working if the server type changes.
- **Frequency rules in logtest** use the time lines are fed in, not the
  timestamps inside them, so replaying the sample file fires them at once.
