#!/bin/bash
set -euo pipefail

source ./scripts/envT2.sh

echo "[+] Pulizia e avvio topologia T2..."
kathara lclean -d "$TOPOLOGY_DIR" || true
sudo kathara lstart -d "$TOPOLOGY_DIR" --privileged
sleep 25

echo "[+] Disconnessione Internet dai nodi..."
./scripts/endInternetConnection.sh
sleep 5

echo "[+] Test connettività interna..."
if kathara exec -d "$TOPOLOGY_DIR" servergm "ping -c 2 boundary0" > /dev/null 2>&1; then
  echo "[✓] Connessione servergm → boundary OK"
else
  echo "[!] Ping servergm → boundary fallito"
fi

if kathara exec -d "$TOPOLOGY_DIR" boundary "ping -c 2 clientptp" > /dev/null 2>&1; then
  echo "[✓] Connessione boundary → clientptp OK"
else
  echo "[!] Ping boundary → clientptp fallito"
fi

if kathara exec -d "$TOPOLOGY_DIR" clientptp "ping -c 2 boundary1" > /dev/null 2>&1; then
  echo "[✓] Connessione clientptp → boundary OK"
else
  echo "[!] Ping clientptp → boundary fallito"
fi

echo "[+] Avvio servizi PTP (grandmaster → boundary → client)..."

# --- Grandmaster ---
echo "   > Avvio PTP su servergm (Grandmaster)..."
kathara exec -d "$TOPOLOGY_DIR" servergm -- bash -lc \
  'ptp4l -f /etc/ptp/server_gm.conf -m -i eth0 -S &> /tesi_sync_lab/analysis/raw_logs/T2/ptp_server.log &'
sleep 3


# --- Boundary Clock ---
echo "   > Avvio PTP su boundary (Boundary Clock)..."
kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc \
  'ptp4l -f /etc/ptp/bc.conf -m -i eth0 -i eth1 -S &> /tesi_sync_lab/analysis/raw_logs/T2/ptp_boundary.log &'
sleep 3

# --- Client PTP ---
echo "   > Avvio PTP su clientptp (Slave)..."
kathara exec -d "$TOPOLOGY_DIR" clientptp -- bash -lc \
  'ptp4l -f /etc/ptp/client_ptp.conf -m -i eth0 -S -s &> /tesi_sync_lab/analysis/raw_logs/T2/ptp_client.log &'
sleep 25

echo "[+] Attesa stabilizzazione PTP..."
sleep 20

echo "[+] Raccolta log di sincronizzazione..."
kathara exec -d "$TOPOLOGY_DIR" clientchrony \
  "chronyc tracking" > analysis/raw_logs/T2/chrony_client.txt || echo "[!] Log Chrony non disponibile"

echo "[+] Raccolta log aggiuntivi Chrony..."
kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc sources -v" > analysis/raw_logs/T2/chrony_sources.txt
kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc sourcestats" > analysis/raw_logs/T2/chrony_sourcestats.txt
kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc rtcdata" > analysis/raw_logs/T2/chrony_rtc.txt
kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc activity" > analysis/raw_logs/T2/chrony_activity.txt


# # sleep 15
# echo "   > Avvio NTPsec su boundary..."
# kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc \
#   'pkill ntpd 2>/dev/null; sleep 2; /usr/sbin/ntpd -g -c /etc/ntpsec/ntp.conf &'
# sleep 15


# kathara exec -d "$TOPOLOGY_DIR" clientntp \
#   "ntpq -p" > analysis/raw_logs/T2/ntp_client.txt || echo "[!] Log NTPsec non disponibile"

# kathara exec -d "$TOPOLOGY_DIR" clientptp \
#   "cat /analysis/raw_logs/T2/ptp_client.log" > analysis/raw_logs/T2/ptp_client.txt || echo "[!] Log PTP non disponibile"

# echo "[+] Tutti i log salvati in analysis/raw_logs/T2/"

# echo "[+] Pulizia processi PTP dai container..."
# for node in servergm boundary clientptp; do
#   kathara exec -d "$TOPOLOGY_DIR" "$node" "pkill ptp4l || true"
# done

# echo "[✓] Test completato con successo."