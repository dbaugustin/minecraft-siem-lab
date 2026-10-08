# Wazuh agent for the Minecraft SIEM lab, run as a container on the server box.
# For boxes where installing the agent on the host isn't convenient (Docker
# Desktop on Windows or macOS). Wazuh publishes no agent image for 4.9.x.
# Build from the wazuh/agent folder so localfile.conf is in the context:
#   docker build -t mc-lab-wazuh-agent -f wazuh/agent/docker/Dockerfile wazuh/agent
FROM ubuntu:22.04
ARG WAZUH_VERSION=4.9.2-1
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg ca-certificates procps \
 && curl -s https://packages.wazuh.com/key/GPG-KEY-WAZUH | gpg --dearmor -o /usr/share/keyrings/wazuh.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/wazuh.gpg] https://packages.wazuh.com/4.x/apt/ stable main" > /etc/apt/sources.list.d/wazuh.list \
 && apt-get update && WAZUH_MANAGER=wazuh.manager WAZUH_AGENT_NAME=mc-lab-box apt-get install -y wazuh-agent=$WAZUH_VERSION \
 && rm -rf /var/lib/apt/lists/*
COPY localfile.conf /tmp/localfile.conf
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
