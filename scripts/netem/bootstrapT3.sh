#!/bin/bash

SCENARIOS=("low" "medium" "high")
#SCENARIOS=("low")
SCENARIO_DIR="$(dirname "$0")/scenarios"
RAWLOG="analysis/raw_logs/T3"
NETNS="boundary"
IFACE="eth1"   # boundary lato rete B
TOPOLOGY_DIR="topologies/T2"

mkdir -p "$RAWLOG"

# for S in "${SCENARIOS[@]}"; do

#     #######################################
#     S C E N A R I O   P T P
#     #######################################

#     echo "=========== SCENARIO $S — PTP ==========="

#     source "$SCENARIO_DIR/$S.conf"

#     kathara lclean -d "$TOPOLOGY_DIR" || true
#     sudo kathara lstart -d "$TOPOLOGY_DIR" --privileged
#     sleep 25

#     # disconnessione internet
#     ./scripts/endInternetConnection.sh
#     sleep 5

#     echo "[DEBUG] delay=$DELAY jitter=$JITTER loss=$LOSS reorder=$REORDER"
#     # applica disturbi
#     kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
#       "tc qdisc replace dev $IFACE root handle 1: netem \
#           delay $DELAY $JITTER \
#           loss $LOSS \
#           reorder $REORDER"


#     # 2) tbf come child di netem
#     kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
#       "tc qdisc add dev $IFACE parent 1: handle 10: tbf \
#           rate $RATE \
#           burst 32kbit \
#           latency 400ms"


#     # log configurazione netem
#     kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
#         "tc qdisc show dev $IFACE" \
#         > "$RAWLOG/netem_state_${S}_ptp.txt"


#     echo "[+] Avvio PTP senza NTP sul boundary..."

#     # Grandmaster
#     kathara exec -d "$TOPOLOGY_DIR" servergm -- bash -lc \
#       "pkill chronyd 2>/dev/null || true; \ #aggiunta questa e sleep 1
      # sleep 1; \
      # ptp4l -f /etc/ptp/server_gm.conf -m -i eth0 -S &> /tesi_sync_lab/$RAWLOG/ptp_server_${S}.log &"
#     sleep 3

#     # Boundary Clock (solo PTP!)
#     kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc \
#       "ptp4l -f /etc/ptp/bc.conf -m -i eth0 -i eth1 -S &> /tesi_sync_lab/$RAWLOG/ptp_boundary_${S}.log &"
#     sleep 3

#     # Client PTP
#     kathara exec -d "$TOPOLOGY_DIR" clientptp -- bash -lc \
#       "ptp4l -f /etc/ptp/client_ptp.conf -m -i eth0 -S -s &> /tesi_sync_lab/$RAWLOG/ptp_client_${S}.log &"

#     echo "[+] Stabilizzazione PTP..."
#     sleep 40

#     # # Chrony
#     # kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc tracking" \
#     #     > "$RAWLOG/chrony_${S}_ptp.log"

#     # # congestione (iperf)
#     # kathara exec -d "$TOPOLOGY_DIR" boundary -- iperf3 -s > /dev/null &
#     # sleep 1
#     # kathara exec -d "$TOPOLOGY_DIR" clientntp -- iperf3 -c boundary -u -b 50M -t 20 \
#     #     > "$RAWLOG/iperf_${S}_ptp.log"

#     kathara lclean -d "$TOPOLOGY_DIR"

# done

# echo "[✓] Tutti i test T3 completati."


    # ########################################
    # # S C E N A R I O   N T P S E C  L O W
    # ########################################

    echo "=========== SCENARIO low— NTPsec ==========="

    source "$SCENARIO_DIR/low.conf"
    echo "[DEBUG] delay=$DELAY jitter=$JITTER loss=$LOSS reorder=$REORDER"

    kathara lclean -d "$TOPOLOGY_DIR" || true
    sudo kathara lstart -d "$TOPOLOGY_DIR" --privileged

    sleep 25
    ./scripts/endInternetConnection.sh
    sleep 5

    kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
       "tc qdisc replace dev $IFACE root handle 1: netem \
            delay $DELAY $JITTER \
            loss $LOSS \
            reorder $REORDER"


    # 2) tbf come child di netem
    kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
        "tc qdisc add dev $IFACE parent 1: handle 10: tbf \
            rate $RATE \
            burst 32kbit \
            latency 400ms"

    kathara exec -d "$TOPOLOGY_DIR" $NETNS -- tc qdisc show dev "$IFACE" \
        > "$RAWLOG/netem_state_${S}_ntpsec.txt"

    echo "[+] Avvio NTPsec SOLO quando serve (PTP spento)."

    # boundary: avvia NTPsec
    kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc \
      'pkill ntpd 2>/dev/null; sleep 2; /usr/sbin/ntpd -g -c /etc/ntpsec/ntp.conf &'
    sleep 15


    kathara exec -d "$TOPOLOGY_DIR" clientntp -- bash -lc '
      nohup bash -c "
        while true; do
          echo \"--- \$(date +%T) ---\"
          ntpq -p
          sleep 60
        done
      " > /tesi_sync_lab/analysis/raw_logs/T3/ntp_clientLOW_live.log 2>&1 &
    '
    kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc '
      nohup bash -c "
        while true; do
          echo \"--- \$(date +%T) ---\"
          ntpq -p
          sleep 60
        done
      " > /tesi_sync_lab/analysis/raw_logs/T3/ntp_boundaryLOW_live.log 2>&1 &
    '


    # ########################################
    # # S C E N A R I O   N T P S E C  M E D I U M
    # ########################################
    # echo "=========== SCENARIO medium- NTPsec ==========="

    # source "$SCENARIO_DIR/medium.conf"
    # echo "[DEBUG] delay=$DELAY jitter=$JITTER loss=$LOSS reorder=$REORDER"


    # kathara lclean -d "$TOPOLOGY_DIR" || true
    # sudo kathara lstart -d "$TOPOLOGY_DIR" --privileged

    # sleep 25
    # ./scripts/endInternetConnection.sh
    # sleep 5

    # kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
    #    "tc qdisc replace dev $IFACE root handle 1: netem \
    #         delay $DELAY $JITTER \
    #         loss $LOSS \
    #         reorder $REORDER"


    # # 2) tbf come child di netem
    # kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
    #     "tc qdisc add dev $IFACE parent 1: handle 10: tbf \
    #         rate $RATE \
    #         burst 32kbit \
    #         latency 400ms"

    # kathara exec -d "$TOPOLOGY_DIR" $NETNS -- tc qdisc show dev "$IFACE" \
    #     > "$RAWLOG/netem_state_${S}_ntpsec.txt"

    # echo "[+] Avvio NTPsec SOLO quando serve (PTP spento)."

    # # boundary: avvia NTPsec
    # kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc \
    #   'pkill ntpd 2>/dev/null; sleep 2; /usr/sbin/ntpd -g -c /etc/ntpsec/ntp.conf &'
    # sleep 15


    # kathara exec -d "$TOPOLOGY_DIR" clientntp -- bash -lc '
    #   nohup bash -c "
    #     while true; do
    #       echo \"--- \$(date +%T) ---\"
    #       ntpq -p
    #       sleep 60
    #     done
    #   " > /tesi_sync_lab/analysis/raw_logs/T3/ntp_clientMEDIUM_live.log 2>&1 &
    # '
    # kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc '
    #   nohup bash -c "
    #     while true; do
    #       echo \"--- \$(date +%T) ---\"
    #       ntpq -p
    #       sleep 60
    #     done
    #   " > /tesi_sync_lab/analysis/raw_logs/T3/ntp_boundaryMEDIUM_live.log 2>&1 &
    # '

# #     # ########################################
# #     # # S C E N A R I O   N T P S E C  H I G H
# #     # ########################################

# echo "=========== SCENARIO high— NTPsec ==========="

#     source "$SCENARIO_DIR/high.conf"
#     echo "[DEBUG] delay=$DELAY jitter=$JITTER loss=$LOSS reorder=$REORDER"


#     kathara lclean -d "$TOPOLOGY_DIR" || true
#     sudo kathara lstart -d "$TOPOLOGY_DIR" --privileged

#     sleep 25
#     ./scripts/endInternetConnection.sh
#     sleep 5

#     kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
#        "tc qdisc replace dev $IFACE root handle 1: netem \
#             delay $DELAY $JITTER \
#             loss $LOSS \
#             reorder $REORDER"


#     # 2) tbf come child di netem
#     kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
#         "tc qdisc add dev $IFACE parent 1: handle 10: tbf \
#             rate $RATE \
#             burst 32kbit \
#             latency 400ms"

#     kathara exec -d "$TOPOLOGY_DIR" $NETNS -- tc qdisc show dev "$IFACE" \
#         > "$RAWLOG/netem_state_${S}_ntpsec.txt"

#     echo "[+] Avvio NTPsec SOLO quando serve (PTP spento)."

#     # boundary: avvia NTPsec
#     kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc \
#       'pkill ntpd 2>/dev/null; sleep 2; /usr/sbin/ntpd -g -c /etc/ntpsec/ntp.conf &'
#     sleep 15


#     kathara exec -d "$TOPOLOGY_DIR" clientntp -- bash -lc '
#       nohup bash -c "
#         while true; do
#           echo \"--- \$(date +%T) ---\"
#           ntpq -p
#           sleep 60
#         done
#       " > /tesi_sync_lab/analysis/raw_logs/T3/ntp_clientHIGH_live.log 2>&1 &
#     '
#     kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc '
#       nohup bash -c "
#         while true; do
#           echo \"--- \$(date +%T) ---\"
#           ntpq -p
#           sleep 60
#         done
#       " > /tesi_sync_lab/analysis/raw_logs/T3/ntp_boundaryHIGH_live.log 2>&1 &
#     '


################################
# S C E N A R I O   C H R O N Y 
################################

# for S in "${SCENARIOS[@]}"; do

#     echo "=========== SCENARIO $S — Chrony ==========="

#     source "$SCENARIO_DIR/$S.conf"
#     echo "[DEBUG] delay=$DELAY jitter=$JITTER loss=$LOSS reorder=$REORDER rate=$RATE"

#     # Cleanup e avvio topologia
#     kathara lclean -d "$TOPOLOGY_DIR" || true
#     sudo kathara lstart -d "$TOPOLOGY_DIR" --privileged

#     mkdir -p "$RAWLOG/chrony_$S"

#     sleep 25
#     ./scripts/endInternetConnection.sh
#     sleep 5

#     echo "[+] Applicazione netem+tbf su clientchrony:eth0..."
#     # kathara exec -d "$TOPOLOGY_DIR" servergm -- bash -lc \
#     #   "tc qdisc replace dev eth0 root handle 1: netem \
#     #         delay $DELAY $JITTER loss $LOSS reorder $REORDER"

#     # kathara exec -d "$TOPOLOGY_DIR" servergm -- bash -lc \
#     #     "tc qdisc add dev eth0 parent 1: handle 10: tbf \
#     #         rate $RATE burst 32kbit latency 400ms"




#   sleep 50


#     CLIENT_IFACE="eth0"   # clientchrony lato rete A

#     kathara exec -d "$TOPOLOGY_DIR" servergm -- bash -lc \
#         "tc qdisc replace dev $CLIENT_IFACE root handle 1: netem \
#             delay $DELAY $JITTER loss $LOSS reorder $REORDER"

#     kathara exec -d "$TOPOLOGY_DIR" servergm -- bash -lc \
#         "tc qdisc add dev $CLIENT_IFACE parent 1: handle 10: tbf \
#             rate $RATE burst 32kbit latency 400ms"

# sleep 45
#     # Stato finale della qdisc (sul client)
#     kathara exec -d "$TOPOLOGY_DIR" servergm -- bash -lc \
#         "tc -s qdisc show dev $CLIENT_IFACE" \
#         > "$RAWLOG/chrony_$S/netem_state_$S.txt"




#     # # Stato finale della qdisc
#     # kathara exec -d "$TOPOLOGY_DIR" servergm -- bash -lc \
#     #     "tc qdisc show dev eth0" \
#     #     > "$RAWLOG/chrony_$S/netem_state_$S.txt"

#     echo "[+] Attesa convergenza Chrony..."
#     sleep 35

#     echo "[+] Raccolta log Chrony..."

#     # kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc tracking" \
#     #   > "$RAWLOG/chrony_$S/chrony_tracking.txt"

#     # kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc sources -v" \
#     #   > "$RAWLOG/chrony_$S/chrony_sources.txt"

#     # kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc sourcestats" \
#     #   > "$RAWLOG/chrony_$S/chrony_sourcestats.txt"

#     # kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc activity" \
#     #   > "$RAWLOG/chrony_$S/chrony_activity.txt"

#     # echo "[+] Scenario $S — Chrony completato."

#     # kathara lclean -d "$TOPOLOGY_DIR"
#     # dopo aver avviato topologia + applicato netem/tbf + atteso un minimo (es. 30–60s)

# SAMPLES=10
# INTERVAL=60

# TRACK_FILE="$RAWLOG/chrony_${S}/chrony_tracking_series.txt"
# SOURCES_FILE="$RAWLOG/chrony_${S}/chrony_sources_series.txt"
# STATS_FILE="$RAWLOG/chrony_${S}/chrony_sourcestats_series.txt"
# ACT_FILE="$RAWLOG/chrony_${S}/chrony_activity_series.txt"


# : > "$TRACK_FILE"
# : > "$SOURCES_FILE"
# : > "$STATS_FILE"
# : > "$ACT_FILE"

# for i in $(seq 1 $SAMPLES); do
#   ts="$(date -Is)"
#   echo "===== SAMPLE $i/$SAMPLES @ $ts =====" | tee -a "$TRACK_FILE" "$SOURCES_FILE" "$STATS_FILE" "$ACT_FILE" >/dev/null

#   kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc tracking" \
#     >> "$TRACK_FILE" 2>&1
#   echo "" >> "$TRACK_FILE"

#   kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc sources -v" \
#     >> "$SOURCES_FILE" 2>&1
#   echo "" >> "$SOURCES_FILE"

#   kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc sourcestats" \
#     >> "$STATS_FILE" 2>&1
#   echo "" >> "$STATS_FILE"

#   kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc activity" \
#     >> "$ACT_FILE" 2>&1
#   echo "" >> "$ACT_FILE"

#   # opzionale: stato qdisc
#   # kathara exec -d "$TOPOLOGY_DIR" clientchrony -- bash -lc "tc -s qdisc show dev eth0" >> "$RAWLOG/chrony_${S}/qdisc_series.txt" 2>&1

#   sleep "$INTERVAL"
# done


# kathara lclean -d "$TOPOLOGY_DIR"
# done