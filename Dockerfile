# syntax=docker/dockerfile:1
# HoneyFactory image: the web UI is built with Node, then served by the Python application together with the
# simulation and the protocol servers (OPC UA, Modbus TCP, embedded MQTT broker). One container, see docker-compose.yml.
#
#   docker build -t honeyfactory:local .
#   docker run -p 8800:8800 -p 4840:4840 -p 1883:1883 -p 5020-5029:5020-5029 -e VF_DEMO=1 -v vf-data:/data honeyfactory:local
#
# The teaching MES (vfmes/) and the Windows desktop client (desktop/) are not part of the server image.
#
# Base images can be replaced, e.g. with a registry mirror:
#   docker build --build-arg NODE_IMAGE=<mirror>/library/node:22-bookworm-slim \
#                --build-arg PYTHON_IMAGE=<mirror>/library/python:3.12-slim-trixie -t honeyfactory:local .
ARG NODE_IMAGE=node:22-bookworm-slim
ARG PYTHON_IMAGE=python:3.12-slim-trixie

# ---- 1. web UI ------------------------------------------------------------------------------------------------
FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS web
# Optional npm registry mirror (empty = registry.npmjs.org)
ARG NPM_REGISTRY=
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund ${NPM_REGISTRY:+--registry "$NPM_REGISTRY"}
COPY web/ ./
RUN npm run build

# ---- 2. runtime -----------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

# VF_HOME: all writable data (accounts database, plants, drafts, versions, recordings, student sandboxes, warm-up
# cache, report templates, config/) goes to /data; the program directory /app stays read-only.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VF_HOME=/data

# Optional package mirrors (empty = official servers), e.g. --build-arg DEBIAN_MIRROR=http://mirrors.example.org
# (replaces http://deb.debian.org) and --build-arg PIP_MIRROR=https://pypi.example.org/simple
ARG DEBIAN_MIRROR=
ARG PIP_MIRROR=

# fonts-wqy-microhei: CJK font for charts in exported reports (Chinese UI and plant names); tzdata: TZ support;
# tini: signal handling as PID 1.
RUN if [ -n "$DEBIAN_MIRROR" ]; then sed -i "s|http://deb.debian.org|$DEBIAN_MIRROR|g" /etc/apt/sources.list.d/debian.sources; fi \
 && apt-get update \
 && apt-get install -y --no-install-recommends fonts-wqy-microhei tzdata tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install ${PIP_MIRROR:+--index-url "$PIP_MIRROR"} -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY vfactory/ ./vfactory/
COPY templates/ ./templates/
# plants/: default model for the command line (python -m vfactory sim|test --config plants/...). The server itself
# runs the plants in /data/plants and creates the demo plant there on first start.
COPY plants/ ./plants/
COPY tests/scripts/ ./tests/scripts/
COPY config/llm.example.json ./config/llm.example.json
COPY --from=web /src/web/dist ./web/dist

RUN useradd --system --uid 10001 --gid 0 --home-dir /app --shell /usr/sbin/nologin honeyfactory \
 && mkdir -p /data \
 && chown -R 10001:0 /data \
 && chmod -R g=u /data

USER 10001
VOLUME ["/data"]
# 8800 web UI and API, 4840 OPC UA, 1883 MQTT, 5020+ Modbus TCP (one port per plant)
EXPOSE 8800 4840 1883 5020-5029

HEALTHCHECK --interval=15s --timeout=5s --start-period=120s --retries=5 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8800/api/health', timeout=4); sys.exit(0)"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "vfactory", "serve", "--http", "8800", "--opcua", "4840", "--mqtt", "1883", "--modbus", "5020"]
