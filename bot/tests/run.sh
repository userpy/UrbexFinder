#!/bin/sh
set -eu
# Schema is prepared by the API migration service.
pytest "$@"
