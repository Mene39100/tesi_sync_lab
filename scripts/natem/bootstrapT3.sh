#!/bin/bash

SCENARIOS=("low" "medium" "high")
SCENARIO_DIR="$(dirname "$0")/scenarios"
RAWLOG="analysis/raw_logs/T3"
NETNS="boundary"
IFACE="eth1"   # boundary lato rete B
TOPOLOGY_DIR="topologies/T2"

mkdir -p "$RAWLOG"

for S in "${SCENARIOS[@]}"; do

    ########################################
    # S C E N A R I O   P T P
    ########################################

    echo "=========== SCENARIO $S — PTP ==========="

    source "$SCENARIO_DIR/$S.conf"

    kathara lclean -d "$TOPOLOGY_DIR" || true
    sudo kathara lstart -d "$TOPOLOGY_DIR" --privileged
    sleep 25

    # disconnessione internet (tu l’hai già così)
    ./scripts/endInternetConnection.sh
    sleep 5

    echo "[DEBUG] delay=$DELAY jitter=$JITTER loss=$LOSS reorder=$REORDER"
    # applica disturbi
    kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
        "tc qdisc replace dev $IFACE root netem \
            delay $DELAY $JITTER \
            loss $LOSS \
            reorder $REORDER" \



    # kathara exec -d "$TOPOLOGY_DIR" $NETNS -- tc qdisc replace dev "$IFACE" tbf \
    #     rate "$RATE" \
    #     burst 32kbit \
    #     latency 400ms

    # log configurazione netem
    kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
        "tc qdisc show dev $IFACE" \
        > "$RAWLOG/netem_state_${S}_ptp.txt"


    echo "[+] Avvio PTP senza NTP sul boundary..."

    # Grandmaster
    kathara exec -d "$TOPOLOGY_DIR" servergm -- bash -lc \
      "ptp4l -f /etc/ptp/server_gm.conf -m -i eth0 -S &> /tesi_sync_lab/analysis/raw_logs/T3/ptp_server_${S}.log &"
    sleep 3

    # Boundary Clock (solo PTP!)
    kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc \
      "ptp4l -f /etc/ptp/bc.conf -m -i eth0 -i eth1 -S &> /tesi_sync_lab/analysis/raw_logs/T3/ptp_boundary_${S}.log &"
    sleep 3

    # Client PTP
    kathara exec -d "$TOPOLOGY_DIR" clientptp -- bash -lc \
      "ptp4l -f /etc/ptp/client_ptp.conf -m -i eth0 -S -s &> /tesi_sync_lab/analysis/raw_logs/T3/ptp_client_${S}.log &"

    echo "[+] Stabilizzazione PTP..."
    sleep 40

    # # Chrony (tranquillo, non interferisce col boundary)
    # kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc tracking" \
    #     > "$RAWLOG/chrony_${S}_ptp.log"

    # # congestione (iperf)
    # kathara exec -d "$TOPOLOGY_DIR" boundary -- iperf3 -s > /dev/null &
    # sleep 1
    # kathara exec -d "$TOPOLOGY_DIR" clientntp -- iperf3 -c boundary -u -b 50M -t 20 \
    #     > "$RAWLOG/iperf_${S}_ptp.log"

    kathara lclean -d "$TOPOLOGY_DIR"



    # ########################################
    # # S C E N A R I O   N T P S E C
    # ########################################

    # echo "=========== SCENARIO $S — NTPsec ==========="

    # kathara lstart -d "$TOPOLOGY_DIR" --privileged
    # sleep 25
    # ./scripts/endInternetConnection.sh
    # sleep 5

    # # disturbi identici allo scenario ptp (per coerenza)
    # kathara exec -d "$TOPOLOGY_DIR" $NETNS -- tc qdisc replace dev "$IFACE" root netem \
    #     delay "$DELAY" "$JITTER" \
    #     loss "$LOSS" \
    #     reorder "$REORDER" \
    #     rate "$RATE"

    # kathara exec -d "$TOPOLOGY_DIR" $NETNS -- tc qdisc show dev "$IFACE" \
    #     > "$RAWLOG/netem_state_${S}_ntpsec.txt"

    # echo "[+] Avvio NTPsec SOLO quando serve (PTP spento)."

    # # boundary: avvia NTPsec (ora sì)
    # kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc \
    #     "pkill ptp4l 2>/dev/null; sleep 2; ntpd -g -c /etc/ntpsec/ntp.conf &"

    # # clientntp
    # kathara exec -d "$TOPOLOGY_DIR" clientntp -- bash -lc \
    #   'nohup bash -c "
    #     echo \"--- NTP CLIENT START ---\"
    #     ntpq -p
    #     sleep 40
    #   " > /tesi_sync_lab/analysis/raw_logs/T3/ntp_client_${S}.log 2>&1 &'

    # sleep 40

    # # log serverntp
    # kathara exec -d "$TOPOLOGY_DIR" serverntp -- ntpq -pn \
    #     > "$RAWLOG/ntpsec_${S}_server.log"

    # # congestione
    # kathara exec -d "$TOPOLOGY_DIR" boundary -- iperf3 -s > /dev/null &
    # sleep 1
    # kathara exec -d "$TOPOLOGY_DIR" clientntp -- iperf3 -c boundary -u -b 50M -t 20 \
    #     > "$RAWLOG/iperf_${S}_ntpsec.log"

    # kathara lclean -d "$TOPOLOGY_DIR"

done

echo "[✓] Tutti i test T3 completati."
