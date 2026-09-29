#!/usr/bin/env bash
exec python3 "$(dirname "$(realpath "$0")")/ctf-control.py" status
