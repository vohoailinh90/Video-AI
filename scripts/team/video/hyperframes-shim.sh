#!/bin/sh
# /usr/local/bin/hyperframes in the video worker image. hyperframes caches Chrome and the Kokoro
# model under $HOME/.cache/hyperframes, but a worker's HOME is an empty tmpfs (read-only
# container). The image bakes both under /opt/hfhome; this links them in, then runs the real CLI.
set -eu
cache="${HOME:-/tmp}/.cache/hyperframes"
if [ ! -e "${cache}/chrome" ]; then
  mkdir -p "${cache}"
  for part in chrome tts; do
    [ -e "/opt/hfhome/.cache/hyperframes/${part}" ] && ln -sfn "/opt/hfhome/.cache/hyperframes/${part}" "${cache}/${part}"
  done
fi
exec /opt/hf/bin/hyperframes "$@"
