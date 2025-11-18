#!/bin/bash

# cleanup_netem.sh <interface>

IF=$1

tc qdisc del dev "$IF" root 2>/dev/null
