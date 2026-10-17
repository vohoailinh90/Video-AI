# Worker image for scripts/team/team.py: a headless coding CLI (OpenCode) plus
# the toolchains the gates need. The same image runs workers and gates.
#
#   docker build -t team-worker:latest /opt/team
#
# Pin OPENCODE_VERSION once a release works for you (`opencode --version`):
# a CLI that changes under an unattended pipeline is a failure you cannot see.
# Add your projects' toolchains here (or build a derived image and point
# TEAM_IMAGE at it) so gates can run offline.
FROM node:22-bookworm-slim

ARG OPENCODE_VERSION=latest

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates git ripgrep curl \
      python3 python3-pip python3-venv python3-pytest \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g "opencode-ai@${OPENCODE_VERSION}" \
 && npm cache clean --force

WORKDIR /work
