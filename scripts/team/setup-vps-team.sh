#!/usr/bin/env bash
# Install the free-model team (scripts/team) on this VPS. Idempotent: rerun it
# after pulling a new version of this repository.
#
#   sudo ./scripts/team/setup-vps-team.sh --admin "$USER" [--with-codex] [--with-video] [--with-hermes] [--no-swap] [--no-build]
#
#   - user `team` (in the docker group) owns /srv/team and runs every worker;
#   - your --admin login joins group `team`, to write specs and run `claude`;
#   - the code is copied root-owned to /opt/team, so neither `team` nor `hermes`
#     can rewrite the conductor that drives them;
#   - /usr/local/bin/team switches to user team for every command that writes,
#     so you always just type `team ...`;
#   - workers get their own docker network, team-net, limited by iptables to the
#     internet: no host services, private ranges or cloud metadata;
#   - --with-hermes creates user `hermes`, which may run `team` as user team and
#     nothing else (a sudoers rule, checked with visudo before it is installed;
#     the wrapper then limits it to status, check-spec, run and doctor).
#   - --with-codex adds a second team whose lead is Codex instead of Claude: its
#     own /srv/team-codex, its own `team-codex` command (the same wrapper under
#     another name), `codex-lead` (the confined launcher for the lead) and its own
#     worker keys. It shares the user, image, network
#     and the first team's pipeline lock. With --with-hermes, hermes gets one more
#     sudoers rule for `team-codex`, in its own file and under the same limits.
#   - --with-video adds a third team that makes HyperFrames videos with sound: its
#     own /srv/team-video, its own `team-video` command and worker keys, and its
#     own image team-video-worker:latest (Chrome, ffmpeg, HyperFrames, a local
#     voice). Same user, network and pipeline lock; Claude is its lead. With
#     --with-hermes it gets its own sudoers rule and skill too.
#
# It never writes an API key and never touches the Actions runner accounts.
# See docs/vps-team.md.
set -euo pipefail

ADMIN="${SUDO_USER:-}"
WITH_HERMES=0
WITH_CODEX=0
WITH_VIDEO=0
SWAP=1
BUILD=1
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX=/opt/team
TEAM_HOME=/srv/team
CODEX_HOME=/srv/team-codex
VIDEO_HOME=/srv/team-video
SWAP_SIZE=4G
WORKER_SUBNET=172.30.99.0/24

usage() { sed -n '2,31p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --admin) ADMIN="$2"; shift 2 ;;
    --with-hermes) WITH_HERMES=1; shift ;;
    --with-codex) WITH_CODEX=1; shift ;;
    --with-video) WITH_VIDEO=1; shift ;;
    --no-swap) SWAP=0; shift ;;
    --no-build) BUILD=0; shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown argument: $1" >&2; usage 1 ;;
  esac
done

# Everything is checked before the first side effect.
[ "$(id -u)" -eq 0 ] || { echo "run it with sudo" >&2; exit 1; }
[ -n "${ADMIN}" ] || { echo "--admin <your login> is required" >&2; exit 1; }
case "${ADMIN}" in
  root|team|hermes) echo "--admin must be your own login, not ${ADMIN}" >&2; exit 1 ;;
esac
id -u "${ADMIN}" >/dev/null 2>&1 || { echo "no such user: ${ADMIN}" >&2; exit 1; }
[ -f "${SRC}/team.py" ] || { echo "${SRC}/team.py not found: run it from a checkout" >&2; exit 1; }

# An existing team-net the egress rules would not cover stops setup before it
# changes anything (no docker yet means no such network).
if command -v docker >/dev/null; then "${SRC}/check-worker-net.sh" "${WORKER_SUBNET}"; fi

echo "== packages"
need=()
command -v docker >/dev/null || need+=(docker.io)
command -v git >/dev/null || need+=(git)
command -v python3 >/dev/null || need+=(python3)
# Codex's Linux sandbox is bubblewrap: without it codex-lead's commands cannot run.
if [ "${WITH_CODEX}" -eq 1 ]; then command -v bwrap >/dev/null || need+=(bubblewrap); fi
if [ "${#need[@]}" -gt 0 ]; then
  apt-get update -q
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q "${need[@]}"
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "python3 >= 3.9 is required" >&2; exit 1; }
getent group docker >/dev/null || { echo "no docker group: install Docker from its apt package" >&2; exit 1; }

if [ "${SWAP}" -eq 1 ] && [ -z "$(swapon --noheadings --show)" ] && [ ! -e /swapfile ]; then
  # 8 GB is tight for CI jobs plus a 3 GB worker container; swap turns an OOM
  # kill into a slowdown.
  echo "== swap ${SWAP_SIZE}"
  fallocate -l "${SWAP_SIZE}" /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== users"
getent group team >/dev/null || groupadd --system team
id -u team >/dev/null 2>&1 || useradd --system --gid team --create-home --home-dir /var/lib/team --shell /bin/bash team
usermod -aG docker team
usermod -aG team "${ADMIN}"
install -d -o team -g team -m 2770 "${TEAM_HOME}" "${TEAM_HOME}/work"
# Created here so `team status` (run as you) never creates it with your umask.
touch "${TEAM_HOME}/.run.lock"
chown team:team "${TEAM_HOME}/.run.lock"
chmod 660 "${TEAM_HOME}/.run.lock"
if [ "${WITH_CODEX}" -eq 1 ]; then
  # No lock file here: team-codex takes the one above, so the two teams never
  # run a pipeline at the same time.
  install -d -o team -g team -m 2770 "${CODEX_HOME}" "${CODEX_HOME}/work"
fi
if [ "${WITH_VIDEO}" -eq 1 ]; then
  install -d -o team -g team -m 2770 "${VIDEO_HOME}" "${VIDEO_HOME}/work"
fi

echo "== code -> ${PREFIX}"
staging="$(mktemp -d /opt/.team.XXXXXX)"
cp -R "${SRC}/." "${staging}/"
find "${staging}" -name '__pycache__' -prune -exec rm -rf {} +
chown -R root:root "${staging}"
chmod -R u=rwX,go=rX "${staging}"
chmod 755 "${staging}/team.py"
rm -rf "${PREFIX}.old"
if [ -d "${PREFIX}" ]; then mv "${PREFIX}" "${PREFIX}.old"; fi
mv "${staging}" "${PREFIX}"
rm -rf "${PREFIX}.old"

install -o root -g root -m 755 "${PREFIX}/team-wrapper.sh" /usr/local/bin/team
if [ "${WITH_CODEX}" -eq 1 ]; then
  # The same file under another name: the wrapper picks the team from its name.
  install -o root -g root -m 755 "${PREFIX}/team-wrapper.sh" /usr/local/bin/team-codex
  # The confined way to start Codex as this team's lead; root-owned so neither the
  # team user nor the hermes user can change what the operator runs.
  install -o root -g root -m 755 "${PREFIX}/codex-lead.sh" /usr/local/bin/codex-lead
fi
if [ "${WITH_VIDEO}" -eq 1 ]; then
  install -o root -g root -m 755 "${PREFIX}/team-wrapper.sh" /usr/local/bin/team-video
fi

echo "== config"
homes=("${TEAM_HOME}")
if [ "${WITH_CODEX}" -eq 1 ]; then homes+=("${CODEX_HOME}"); fi
if [ "${WITH_VIDEO}" -eq 1 ]; then homes+=("${VIDEO_HOME}"); fi
for home in "${homes[@]}"; do
  for name in team.env workers.env; do
    if [ ! -e "${home}/${name}" ]; then
      mode=660
      [ "${name}" = workers.env ] && mode=600
      example="${PREFIX}/${name}.example"
      # The video team starts from its own team.env: its image, memory and /dev/shm differ.
      if [ "${home}" = "${VIDEO_HOME}" ] && [ "${name}" = team.env ]; then example="${PREFIX}/team.env.video.example"; fi
      install -o team -g team -m "${mode}" "${example}" "${home}/${name}"
      echo "created ${home}/${name}: fill it in"
    fi
  done
done

echo "== worker network team-net (internet only)"
# Workers need the internet for their model API and nothing else: not this host
# (CI runner, Hermes), not private ranges, not the cloud metadata service at
# 169.254.169.254. The rules live in a oneshot unit so they return after reboot.
docker network inspect team-net >/dev/null 2>&1 || docker network create --subnet "${WORKER_SUBNET}" team-net >/dev/null
cat > /usr/local/sbin/team-egress <<EGRESS
#!/usr/bin/env bash
set -euo pipefail
subnet=${WORKER_SUBNET}
for dest in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10; do
  iptables -C DOCKER-USER -s "\${subnet}" -d "\${dest}" -j DROP 2>/dev/null \\
    || iptables -I DOCKER-USER -s "\${subnet}" -d "\${dest}" -j DROP
done
iptables -C INPUT -s "\${subnet}" -j DROP 2>/dev/null || iptables -I INPUT -s "\${subnet}" -j DROP
EGRESS
chmod 755 /usr/local/sbin/team-egress
cat > /etc/systemd/system/team-egress.service <<'UNIT'
[Unit]
Description=Egress limits for team worker containers
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/team-egress
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT
if command -v iptables >/dev/null; then
  systemctl daemon-reload
  systemctl enable --now team-egress.service >/dev/null
  systemctl restart team-egress.service
else
  echo "WARNING: iptables not found: team-net is NOT egress-limited" >&2
fi

if [ "${BUILD}" -eq 1 ]; then
  echo "== image team-worker:latest (a few minutes the first time)"
  docker build -q -t team-worker:latest "${PREFIX}"
  if [ "${WITH_VIDEO}" -eq 1 ]; then
    echo "== image team-video-worker:latest (Chrome, ffmpeg, HyperFrames and a voice model: ~1.5 GB, several minutes)"
    docker build -q -t team-video-worker:latest -f "${PREFIX}/Dockerfile.video" "${PREFIX}"
  fi
fi

if [ "${WITH_HERMES}" -eq 1 ]; then
  echo "== hermes"
  id -u hermes >/dev/null 2>&1 || useradd --create-home --shell /bin/bash hermes
  # The docker group is root on this box. Hermes is driven by a free model
  # reading chat messages; it gets the team wrapper and nothing else.
  if id -nG hermes | tr ' ' '\n' | grep -qx -e docker -e team -e sudo; then
    echo "user hermes is in docker, team or sudo: remove it from those groups first" >&2
    exit 1
  fi
  rule="$(mktemp)"
  printf 'hermes ALL=(team) NOPASSWD: /usr/local/bin/team\n' > "${rule}"
  visudo -cf "${rule}" >/dev/null
  install -o root -g root -m 440 "${rule}" /etc/sudoers.d/team-hermes
  rm -f "${rule}"
  skill_dir="$(getent passwd hermes | cut -d: -f6)/.hermes/skills/team-pipeline"
  runuser -u hermes -- mkdir -p "${skill_dir}"
  install -o hermes -g hermes -m 644 "${PREFIX}/hermes/SKILL.md" "${skill_dir}/SKILL.md"
  if [ "${WITH_CODEX}" -eq 1 ]; then
    # A rule of its own, so removing the Codex team never touches the first one.
    codex_rule="$(mktemp)"
    printf 'hermes ALL=(team) NOPASSWD: /usr/local/bin/team-codex\n' > "${codex_rule}"
    visudo -cf "${codex_rule}" >/dev/null
    install -o root -g root -m 440 "${codex_rule}" /etc/sudoers.d/team-codex-hermes
    rm -f "${codex_rule}"
    codex_skill_dir="$(getent passwd hermes | cut -d: -f6)/.hermes/skills/team-codex-pipeline"
    runuser -u hermes -- mkdir -p "${codex_skill_dir}"
    install -o hermes -g hermes -m 644 "${PREFIX}/hermes/SKILL-codex.md" "${codex_skill_dir}/SKILL.md"
  fi
  if [ "${WITH_VIDEO}" -eq 1 ]; then
    video_rule="$(mktemp)"
    printf 'hermes ALL=(team) NOPASSWD: /usr/local/bin/team-video\n' > "${video_rule}"
    visudo -cf "${video_rule}" >/dev/null
    install -o root -g root -m 440 "${video_rule}" /etc/sudoers.d/team-video-hermes
    rm -f "${video_rule}"
    video_skill_dir="$(getent passwd hermes | cut -d: -f6)/.hermes/skills/team-video-pipeline"
    runuser -u hermes -- mkdir -p "${video_skill_dir}"
    install -o hermes -g hermes -m 644 "${PREFIX}/hermes/SKILL-video.md" "${video_skill_dir}/SKILL.md"
  fi
fi

cat <<EOF

Done. Next (docs/vps-team.md):
  1. log out and back in as ${ADMIN} (new group: team)
  2. sudo -u team nano ${TEAM_HOME}/workers.env      # worker API keys, never a Claude key
  3. team models openrouter --free; team models google; team models mistral
  4. nano ${TEAM_HOME}/team.env                       # pick the models per role
  5. team doctor --ping
EOF
if [ "${WITH_CODEX}" -eq 1 ]; then
  cat <<EOF

Codex team (docs/vps-team-codex.md): same steps, its own files and command.
  1. sudo -u team nano ${CODEX_HOME}/workers.env      # worker keys; never your Codex login
  2. nano ${CODEX_HOME}/team.env                       # pick the models per role
  3. team-codex doctor --ping
  4. CODEX_HOME="\$HOME/.codex-lead" codex login      # as ${ADMIN}, once; the lead runs only in your login, in this profile
EOF
fi
if [ "${WITH_VIDEO}" -eq 1 ]; then
  cat <<EOF

Video team (docs/vps-team-video.md): same steps, its own files and command.
  1. sudo -u team nano ${VIDEO_HOME}/workers.env      # worker keys; never your Claude login
  2. nano ${VIDEO_HOME}/team.env                       # pick the models per role
  3. team-video doctor --ping --smoke                  # --smoke renders a test video with sound inside the image
EOF
fi
