#!/bin/sh
# Run Kinema without installing
cd "$(dirname "$0")"
export GSETTINGS_SCHEMA_DIR=data
export GSK_RENDERER=gl
exec python3 -m kinema.main "$@"
