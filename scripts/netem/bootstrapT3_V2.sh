#!/bin/bash

SCENARIOS=("low" "medium" "high")
SCENARIO_DIR="$(dirname "$0")/scenarios"
RAWLOG_ROOT="analysis/raw_logs/T3_multiplerun"
NETNS="boundary"
IFACE="eth1"   # boundary lato rete B
TOPOLOGY_DIR="topologies/T2"

RUNS=15

mkdir -p "$RAWLOG_ROOT"

run_ptp_scenario() {
    local S="$1"
    local RUN_ID="$2"
    local RUN_DIR="$RAWLOG_ROOT/ptp/$S/run$(printf "%02d" "$RUN_ID")"

    mkdir -p "$RUN_DIR"

    echo "=========== SCENARIO $S — PTP — RUN $(printf "%02d" "$RUN_ID") ==========="

    source "$SCENARIO_DIR/$S.conf"

    kathara lclean -d "$TOPOLOGY_DIR" || true
    #sudo kathara lstart -d "$TOPOLOGY_DIR" --privileged
    sudo -v
    printf 'n\n' | sudo -n kathara lstart -d "$TOPOLOGY_DIR" --privileged
    sleep 25

    ./scripts/endInternetConnection.sh
    sleep 5

    echo "[DEBUG] delay=$DELAY jitter=$JITTER loss=$LOSS reorder=$REORDER"

    kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
      "tc qdisc replace dev $IFACE root handle 1: netem \
          delay $DELAY $JITTER \
          loss $LOSS \
          reorder $REORDER"

    kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
      "tc qdisc add dev $IFACE parent 1: handle 10: tbf \
          rate $RATE \
          burst 32kbit \
          latency 400ms"

    kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
        "tc qdisc show dev $IFACE" \
        > "$RUN_DIR/netem_state.txt"

    echo "[+] Avvio PTP senza NTP sul boundary..."

    kathara exec -d "$TOPOLOGY_DIR" servergm -- bash -lc \
      "pkill chronyd 2>/dev/null || true; \
      sleep 1; \
      ptp4l -f /etc/ptp/server_gm.conf -m -i eth0 -S &> /tesi_sync_lab/$RUN_DIR/ptp_server.log &"
    sleep 3

    kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc \
      "ptp4l -f /etc/ptp/bc.conf -m -i eth0 -i eth1 -S &> /tesi_sync_lab/$RUN_DIR/ptp_boundary.log &"
    sleep 3

    kathara exec -d "$TOPOLOGY_DIR" clientptp -- bash -lc \
      "ptp4l -f /etc/ptp/client_ptp.conf -m -i eth0 -S -s &> /tesi_sync_lab/$RUN_DIR/ptp_client.log &"

    echo "[+] Stabilizzazione PTP..."
    sleep 250

    kathara lclean -d "$TOPOLOGY_DIR"
}

run_ntpsec_scenario() {
    local S="$1"
    local RUN_ID="$2"
    local RUN_DIR="$RAWLOG_ROOT/ntpsec/$S/run$(printf "%02d" "$RUN_ID")"

    mkdir -p "$RUN_DIR"

    echo "=========== SCENARIO $S — NTPsec — RUN $(printf "%02d" "$RUN_ID") ==========="

    source "$SCENARIO_DIR/$S.conf"
    echo "[DEBUG] delay=$DELAY jitter=$JITTER loss=$LOSS reorder=$REORDER"

    kathara lclean -d "$TOPOLOGY_DIR" || true
    #sudo kathara lstart -d "$TOPOLOGY_DIR" --privileged
    sudo -v
    printf 'n\n' | sudo -n kathara lstart -d "$TOPOLOGY_DIR" --privileged
    sleep 25
    ./scripts/endInternetConnection.sh
    sleep 5

    kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
       "tc qdisc replace dev $IFACE root handle 1: netem \
            delay $DELAY $JITTER \
            loss $LOSS \
            reorder $REORDER"

    kathara exec -d "$TOPOLOGY_DIR" $NETNS -- bash -lc \
        "tc qdisc add dev $IFACE parent 1: handle 10: tbf \
            rate $RATE \
            burst 32kbit \
            latency 400ms"

    kathara exec -d "$TOPOLOGY_DIR" $NETNS -- tc qdisc show dev "$IFACE" \
        > "$RUN_DIR/netem_state.txt"

    echo "[+] Avvio NTPsec SOLO quando serve (PTP spento)."

    kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc \
      'pkill ntpd 2>/dev/null; sleep 2; /usr/sbin/ntpd -g -c /etc/ntpsec/ntp.conf &'
    sleep 15

    kathara exec -d "$TOPOLOGY_DIR" clientntp -- bash -lc "
      nohup bash -c '
        while true; do
          echo \"--- \$(date +%T) ---\"
          ntpq -p
          sleep 15
        done
      ' > /tesi_sync_lab/$RUN_DIR/ntp_client_live.log 2>&1 &
    "

    kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc "
      nohup bash -c '
        while true; do
          echo \"--- \$(date +%T) ---\"
          ntpq -p
          sleep 15
        done
      ' > /tesi_sync_lab/$RUN_DIR/ntp_boundary_live.log 2>&1 &
    "

    sleep 1500

    kathara lclean -d "$TOPOLOGY_DIR"
}


##########
# doppia funzione run_chrony_scenario_* configurando rispettivamente il netem/tc su servergm e su clientchrony in due run separate
##########
run_chrony_scenario_servergm() {
    local S="$1"
    local RUN_ID="$2"
    local RUN_DIR="$RAWLOG_ROOT/chrony_servergm/$S/run$(printf "%02d" "$RUN_ID")"

    mkdir -p "$RUN_DIR"

    echo "=========== SCENARIO $S — Chrony — RUN $(printf "%02d" "$RUN_ID") ==========="

    source "$SCENARIO_DIR/$S.conf"
    echo "[DEBUG] delay=$DELAY jitter=$JITTER loss=$LOSS reorder=$REORDER rate=$RATE"

    kathara lclean -d "$TOPOLOGY_DIR" || true
    #sudo kathara lstart -d "$TOPOLOGY_DIR" --privileged
    sudo -v
    printf 'n\n' | sudo -n kathara lstart -d "$TOPOLOGY_DIR" --privileged
    sleep 25
    ./scripts/endInternetConnection.sh
    sleep 5

    echo "[+] Applicazione netem+tbf su servergm:eth0..."

    sleep 50

    CLIENT_IFACE="eth0"   # clientchrony lato rete A

    kathara exec -d "$TOPOLOGY_DIR" servergm -- bash -lc \
        "tc qdisc replace dev $CLIENT_IFACE root handle 1: netem \
            delay $DELAY $JITTER loss $LOSS reorder $REORDER"

    kathara exec -d "$TOPOLOGY_DIR" servergm -- bash -lc \
        "tc qdisc add dev $CLIENT_IFACE parent 1: handle 10: tbf \
            rate $RATE burst 32kbit latency 400ms"

    sleep 45

    kathara exec -d "$TOPOLOGY_DIR" servergm -- bash -lc \
        "tc -s qdisc show dev $CLIENT_IFACE" \
        > "$RUN_DIR/netem_state.txt"

    echo "[+] Attesa convergenza Chrony..."
    sleep 35

    echo "[+] Raccolta log Chrony..."

    SAMPLES=10
    INTERVAL=60

    TRACK_FILE="$RUN_DIR/chrony_tracking_series.txt"
    SOURCES_FILE="$RUN_DIR/chrony_sources_series.txt"
    STATS_FILE="$RUN_DIR/chrony_sourcestats_series.txt"
    ACT_FILE="$RUN_DIR/chrony_activity_series.txt"

    : > "$TRACK_FILE"
    : > "$SOURCES_FILE"
    : > "$STATS_FILE"
    : > "$ACT_FILE"

    for i in $(seq 1 $SAMPLES); do
      ts="$(date -Is)"
      echo "===== SAMPLE $i/$SAMPLES @ $ts =====" | tee -a "$TRACK_FILE" "$SOURCES_FILE" "$STATS_FILE" "$ACT_FILE" >/dev/null

      kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc tracking" \
        >> "$TRACK_FILE" 2>&1
      echo "" >> "$TRACK_FILE"

      kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc sources -v" \
        >> "$SOURCES_FILE" 2>&1
      echo "" >> "$SOURCES_FILE"

      kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc sourcestats" \
        >> "$STATS_FILE" 2>&1
      echo "" >> "$STATS_FILE"

      kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc activity" \
        >> "$ACT_FILE" 2>&1
      echo "" >> "$ACT_FILE"

      sleep "$INTERVAL"
    done

    kathara lclean -d "$TOPOLOGY_DIR"
}

run_chrony_scenario_clientchrony() {
    local S="$1"
    local RUN_ID="$2"
    local RUN_DIR="$RAWLOG_ROOT/chrony_clientchrony/$S/run$(printf "%02d" "$RUN_ID")"

    mkdir -p "$RUN_DIR"

    echo "=========== SCENARIO $S — Chrony — RUN $(printf "%02d" "$RUN_ID") ==========="

    source "$SCENARIO_DIR/$S.conf"
    echo "[DEBUG] delay=$DELAY jitter=$JITTER loss=$LOSS reorder=$REORDER rate=$RATE"

    kathara lclean -d "$TOPOLOGY_DIR" || true
    #sudo kathara lstart -d "$TOPOLOGY_DIR" --privileged
    sudo -v
    printf 'n\n' | sudo -n kathara lstart -d "$TOPOLOGY_DIR" --privileged
    sleep 25
    ./scripts/endInternetConnection.sh
    sleep 5

    echo "[+] Applicazione netem+tbf su clientchrony:eth0..."

    sleep 50

    CLIENT_IFACE="eth0"   # clientchrony lato rete A

    kathara exec -d "$TOPOLOGY_DIR" clientchrony -- bash -lc \
        "tc qdisc replace dev $CLIENT_IFACE root handle 1: netem \
            delay $DELAY $JITTER loss $LOSS reorder $REORDER"

    kathara exec -d "$TOPOLOGY_DIR" clientchrony -- bash -lc \
        "tc qdisc add dev $CLIENT_IFACE parent 1: handle 10: tbf \
            rate $RATE burst 32kbit latency 400ms"

    sleep 45

    kathara exec -d "$TOPOLOGY_DIR" clientchrony -- bash -lc \
        "tc -s qdisc show dev $CLIENT_IFACE" \
        > "$RUN_DIR/netem_state.txt"

    echo "[+] Attesa convergenza Chrony..."
    sleep 35

    echo "[+] Raccolta log Chrony..."

    SAMPLES=20
    INTERVAL=60

    TRACK_FILE="$RUN_DIR/chrony_tracking_series.txt"
    SOURCES_FILE="$RUN_DIR/chrony_sources_series.txt"
    STATS_FILE="$RUN_DIR/chrony_sourcestats_series.txt"
    ACT_FILE="$RUN_DIR/chrony_activity_series.txt"

    : > "$TRACK_FILE"
    : > "$SOURCES_FILE"
    : > "$STATS_FILE"
    : > "$ACT_FILE"

    for i in $(seq 1 $SAMPLES); do
      ts="$(date -Is)"
      echo "===== SAMPLE $i/$SAMPLES @ $ts =====" | tee -a "$TRACK_FILE" "$SOURCES_FILE" "$STATS_FILE" "$ACT_FILE" >/dev/null

      kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc tracking" \
        >> "$TRACK_FILE" 2>&1
      echo "" >> "$TRACK_FILE"

      kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc sources -v" \
        >> "$SOURCES_FILE" 2>&1
      echo "" >> "$SOURCES_FILE"

      kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc sourcestats" \
        >> "$STATS_FILE" 2>&1
      echo "" >> "$STATS_FILE"

      kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc activity" \
        >> "$ACT_FILE" 2>&1
      echo "" >> "$ACT_FILE"

      sleep "$INTERVAL"
    done

    kathara lclean -d "$TOPOLOGY_DIR"
}

#######################################
# ESECUZIONE
#######################################

for S in "${SCENARIOS[@]}"; do
    for RUN_ID in $(seq 1 $RUNS); do
        run_ptp_scenario "$S" "$RUN_ID"
    done
done

for S in "${SCENARIOS[@]}"; do
    for RUN_ID in $(seq 1 $RUNS); do
        run_ntpsec_scenario "$S" "$RUN_ID"
    done
done

for S in "${SCENARIOS[@]}"; do
    for RUN_ID in $(seq 1 $RUNS); do
        run_chrony_scenario_servergm "$S" "$RUN_ID"
    done
done

for S in "${SCENARIOS[@]}"; do
    for RUN_ID in $(seq 1 $RUNS); do
        run_chrony_scenario_clientchrony "$S" "$RUN_ID"
    done
done

echo "[✓] Tutti i test T3 completati."