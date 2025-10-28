#!/bin/bash
set -e
source "$(dirname "$0")/env_T2.sh"

echo "[+] Pulizia ambiente e avvio topologia..."
lclean
lstart

echo "[+] Attesa avvio container..."
sleep 10

echo "[+] Test connettività base..."
lcmd serverGM ping -c 2 boundary
lcmd boundary ping -c 2 clientPTP

echo "[+] Avvio servizi PTP..."
lcmd serverGM "ptp4l -f /etc/ptp/server_gm.conf -m -i eth0 -s > /tmp/ptp_server.log 2>&1 &"
lcmd boundary "ptp4l -f /etc/ptp/bc.conf -m -i eth0 -i eth1 -s > /tmp/ptp_boundary.log 2>&1 &"
lcmd clientPTP "ptp4l -f /etc/ptp/client_ptp.conf -m -i eth0 > /tmp/ptp_client.log 2>&1 &"

echo "[+] Attesa stabilizzazione PTP..."
sleep 20

echo "[+] Raccolta log sincronizzazione..."
mkdir -p "$LOG_DIR"
lcmd clientChrony chronyc tracking > "$LOG_DIR/chrony_client.txt"
lcmd clientNTP ntpq -p > "$LOG_DIR/ntp_client.txt"
lcmd clientPTP cat /tmp/ptp_client.log > "$LOG_DIR/ptp_client.txt"

echo "[+] Salvataggio completato in $LOG_DIR"
echo "[+] Test terminato con successo!"
