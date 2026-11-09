#!/bin/sh
set -e

# If running as root, ensure ownership of mounted volumes and drop privileges to manara
if [ "$(id -u)" = "0" ]; then
    mkdir -p /state /published /home/manara
    chown -R manara:manara /state /published /home/manara 2>/dev/null || true
    exec setpriv --reuid=manara --regid=manara --init-groups "$@"
fi

exec "$@"
