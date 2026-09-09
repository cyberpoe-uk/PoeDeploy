#!/usr/bin/env bash
# A harmless foreground package/build process for terminal signal tests.
set -e
trap 'sleep 0.2; printf "PACKAGE_EXITED\n"; exit 130' INT
printf 'PACKAGE_READY\n'
sleep 30
