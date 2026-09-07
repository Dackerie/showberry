#!/bin/sh
# Run Showberry without installing
cd "$(dirname "$0")"
export GSETTINGS_SCHEMA_DIR=data
export GSK_RENDERER=gl
if [ -f /usr/lib/libcurl-impersonate.so.4 ]; then
    export LD_PRELOAD="/usr/lib/libcurl-impersonate.so.4${LD_PRELOAD:+:$LD_PRELOAD}"
fi
exec python3 -m kinema.main "$@"
