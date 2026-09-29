#!/usr/bin/env bash
case "$1" in
    system) exec kitty --class dashboard-btop btop ;;
    gpu) exec kitty --class dashboard-nvtop nvtop ;;
    network) exec kitty --class dashboard-network sh -c 'ip -brief address; printf "\nROUTES\n"; ip route; printf "\nPress Enter to close"; read -r answer' ;;
    updates) exec kitty --class dashboard-updates sh -c 'checkupdates; result=$?; if [ "$result" = 2 ]; then echo "System is up to date."; elif [ "$result" != 0 ]; then echo "Update check failed."; fi; printf "\nPress Enter to close"; read -r answer' ;;
    *) exit 2 ;;
esac
