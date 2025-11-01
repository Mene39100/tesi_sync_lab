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
if kathara exec -d "$TOPOLOGY_DIR" servergm "ping -c 2 boundary" > /dev/null 2>&1; then
  echo "[✓] Connessione servergm → boundary OK"
else
  echo "[!] Ping servergm → boundary fallito"
fi

if kathara exec -d "$TOPOLOGY_DIR" boundary "ping -c 2 clientptp" > /dev/null 2>&1; then
  echo "[✓] Connessione boundary → clientptp OK"
else
  echo "[!] Ping boundary → clientptp fallito"
fi

echo "[+] Avvio servizi PTP (grandmaster → boundary → client)..."

# --- Grandmaster ---
echo "   > Avvio PTP su servergm (Grandmaster)..."
kathara exec -d "$TOPOLOGY_DIR" servergm -- bash -lc \
  'ptp4l -f /etc/ptp/server_gm.conf -m -i eth0 -S &> /analysis/raw_logs/T2/ptp_server.log &'
sleep 3


# --- Boundary Clock ---
echo "   > Avvio PTP su boundary (Boundary Clock)..."
kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc \
  'ptp4l -f /etc/ptp/bc.conf -m -i eth0 -i eth1 -S &> /analysis/raw_logs/T2/ptp_boundary.log &'
sleep 3

# --- Client PTP ---
echo "   > Avvio PTP su clientptp (Slave)..."
kathara exec -d "$TOPOLOGY_DIR" clientptp -- bash -lc \
  'ptp4l -f /etc/ptp/client_ptp.conf -m -i eth0 -S -s > /analysis/raw_logs/T2/ptp_client.log &'
sleep 15

echo "[+] Attesa stabilizzazione PTP..."
# sleep 20

# echo "[+] Raccolta log di sincronizzazione..."
# kathara exec -d "$TOPOLOGY_DIR" clientchrony \
#   "chronyc tracking" > analysis/raw_logs/T2/chrony_client.txt || echo "[!] Log Chrony non disponibile"

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

########################################################################################
#VECCHIO SCRIPT
########################################################################################

# set -euo pipefail

# source ./scripts/envT2.sh

# echo "[+] Pulizia e avvio topologia T2..."
# kathara lclean -d "$TOPOLOGY_DIR" || true
# kathara lstart -d "$TOPOLOGY_DIR"
# sleep 10

# echo "[+] Disconnessione Internet dai nodi..."
# ./scripts/endInternetConnection.sh
# sleep 5

# echo "[+] Test connettività interna..."
# kathara exec -d "$TOPOLOGY_DIR" servergm "ping -c 2 boundary" || echo "[!] Ping servergm→boundary fallito"
# kathara exec -d "$TOPOLOGY_DIR" boundary "ping -c 2 clientptp" || echo "[!] Ping boundary→clientptp fallito"

# echo "[+] Avvio servizi PTP (grandmaster → boundary → client)..."

# # --- Grandmaster ---
# kathara exec -d "$TOPOLOGY_DIR" servergm -- bash -lc \
# 'ptp4l -f /etc/ptp/server_gm.conf -m -i eth0 -s &> /analysis/raw_logs/T2/ptp_server.log &'
# sleep 3

# # --- Boundary Clock ---
# kathara exec -d "$TOPOLOGY_DIR" boundary -- bash -lc \
# 'ptp4l -f /etc/ptp/bc.conf -m -i eth1 -s &> /analysis/raw_logs/T2/ptp_boundary.log &'
# sleep 3

# # --- Client PTP ---
# kathara exec -d "$TOPOLOGY_DIR" clientptp -- bash -lc \
# 'ptp4l -f /etc/ptp/client_ptp.conf -m -i eth0 -s &> /analysis/raw_logs/T2/ptp_client.log &'
# sleep 5



# --- Attesa stabilizzazione PTP (opzionale) ---
# echo "[+] Attesa stabilizzazione PTP..."
# sleep 25

# --- Raccolta log di sincronizzazione ---
# echo "[+] Raccolta log di sincronizzazione..."
# kathara exec -d "$TOPOLOGY_DIR" clientchrony "chronyc tracking" \
#   > analysis/raw_logs/T2/chrony_client.log 2>&1 || echo "[!] Log Chrony non disponibile"
# kathara exec -d "$TOPOLOGY_DIR" clientntp "ntpq -p" \
#   > analysis/raw_logs/T2/ntp_client.log 2>&1 || echo "[!] Log NTPsec non disponibile"

# echo "[+] Tutti i log salvati in analysis/raw_logs/T2/"
# echo "[✓] Test completato con successo."
