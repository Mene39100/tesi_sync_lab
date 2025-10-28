#!/bin/bash
set -e
cd "$(dirname "$0")"
bash ./bootstrapT2.sh

echo "[+] Controllo offset Chrony..."
grep -i "offset" ../analysis/raw_logs/T2/chrony_client.txt || echo "Chrony non sincronizzato"

echo "[+] Controllo NTPsec..."
grep "\*" ../analysis/raw_logs/T2/ntp_client.txt || echo "NTPsec non sincronizzato"

echo "[+] Ultime righe log PTP..."
tail -n 5 ../analysis/raw_logs/T2/ptp_client.txt || true

