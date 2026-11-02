#!/usr/bin/env bash
# Give this PC an address on the hand's subnet (the hand has no DHCP server).
#
#   scripts/setup-network.sh               # temporary: until the cable/link resets
#   scripts/setup-network.sh --persistent  # stored in the NetworkManager profile
#
# Env overrides: IFACE (default eno2), HOST_ADDR (192.168.11.100/24), HAND_IP.
set -euo pipefail

iface="${IFACE:-eno2}"
addr="${HOST_ADDR:-192.168.11.100/24}"
hand="${HAND_IP:-192.168.11.210}"

if ip -br addr show "$iface" | grep -qw "$addr"; then
    echo "$iface already has $addr"
elif [[ "${1:-}" == "--persistent" ]]; then
    profile="$(nmcli -g GENERAL.CONNECTION device show "$iface")"
    echo "adding $addr to NetworkManager profile '$profile'"
    nmcli connection modify "$profile" +ipv4.addresses "$addr"
    nmcli device reapply "$iface"
else
    echo "adding $addr to $iface (temporary)"
    nmcli device modify "$iface" +ipv4.addresses "$addr"
fi

if timeout 2 bash -c "echo > /dev/tcp/$hand/6000" 2>/dev/null; then
    echo "hand reachable at $hand:6000"
else
    echo "no answer from $hand:6000; check power, cable and the hand's IP" >&2
    exit 1
fi
