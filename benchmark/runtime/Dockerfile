FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ARG NODE_VERSION=22.20.0
RUN apt-get update -qq && apt-get install -y --no-install-recommends curl ca-certificates xz-utils \
    && rm -rf /var/lib/apt/lists/*
RUN case "$(uname -m)" in x86_64) arch=x64;; aarch64) arch=arm64;; *) exit 1;; esac \
    && mkdir -p /opt/benchflow/node \
    && curl -fSL --connect-timeout 20 --max-time 600 --retry 2 --output /tmp/node.tar.xz \
       "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${arch}.tar.xz" \
    && tar -xJf /tmp/node.tar.xz -C /opt/benchflow/node --strip-components=1 \
    && rm /tmp/node.tar.xz
ENV PATH="/opt/benchflow/bin:/opt/benchflow/js-agents/bin:/opt/benchflow/node/bin:${PATH}"
RUN --mount=type=cache,id=skills-benchmark-npm,target=/root/.npm \
    npm install -g --prefix /opt/benchflow/js-agents \
        @agentclientprotocol/codex-acp@2.6.0 @openai/codex@0.166.0 \
    && mkdir -p /opt/benchflow/bin \
    && printf '%s\n' '#!/bin/sh' 'exec /opt/benchflow/node/bin/node /opt/benchflow/js-agents/bin/codex-acp "$@"' \
       > /opt/benchflow/bin/codex-acp \
    && chmod +x /opt/benchflow/bin/codex-acp && chmod -R a+rX /opt/benchflow
