#!/bin/bash
bash "$(dirname "$0")/bootstrapT2.sh"

echo "[+] Verifica offset Chrony..."
grep "Offset" ../analysis/raw_logs/T2/chrony_client.txt || echo "Offset non trovato."

echo "[+] Verifica sincronizzazione NTP..."
grep "\*" ../analysis/raw_logs/T2/ntp_client.txt || echo "NTP non sincronizzato."

echo "[+] Verifica log PTP..."
grep "offset" ../analysis/raw_logs/T2/ptp_client.txt | tail -5
