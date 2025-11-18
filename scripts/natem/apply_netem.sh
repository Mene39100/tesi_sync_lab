#!/bin/bash

# apply_netem.sh <interface> <mode> <param1> <param2>

IF=$1
MODE=$2
PARAM1=$3
PARAM2=$4

case "$MODE" in

  delay)
    tc qdisc replace dev "$IF" root netem delay "$PARAM1"
    ;;

  delay_jitter)
    tc qdisc replace dev "$IF" root netem delay "$PARAM1" "$PARAM2"
    ;;

  loss)
    tc qdisc replace dev "$IF" root netem loss "$PARAM1"
    ;;

  reorder)
    tc qdisc replace dev "$IF" root netem reorder "$PARAM1"
    ;;

  rate)
    tc qdisc replace dev "$IF" root netem rate "$PARAM1"
    ;;

  *)
    echo "Errore: modalità sconosciuta ($MODE)"
    exit 1
    ;;

esac
