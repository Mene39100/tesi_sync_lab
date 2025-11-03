#!/bin/bash
set -e

# Carica variabili da file env.sh
source "$(dirname "$0")/env.sh"

# Specifica il percorso della topologia

# Avvia il lab
# Avvia il laboratorio
kathara lclean -d $TOPOLOGY_DIR
kathara lstart -d $TOPOLOGY_DIR

# Attendi che i container siano pienamente attivi
echo "[+] Waiting for containers to be fully up..."
sleep 20

kathara list

mkdir -p analysis/raw_logs/T1

#------------------------------Ping client&server-----------------------------------------#
echo "[+] Testing ping from client to server" && echo "[+] Testing ping from client to server" >> analysis/raw_logs/T1/ping_client_server.log
kathara exec -d $TOPOLOGY_DIR clientntp "ping -c 5 $SERVER_IP" >> analysis/raw_logs/T1/ping_client_server.log 2>&1

echo "[+] Testing ping from server to client" && echo "[+] Testing ping from server to client" >> analysis/raw_logs/T1/ping_server_client.log
kathara exec -d $TOPOLOGY_DIR server "ping -c 5 $CLIENT_IP" >> analysis/raw_logs/T1/ping_server_client.log 2>&1

echo "[+] Ping tests done"
echo "[+] ping tests completed ($(date))" >> analysis/raw_logs/T1/ping_client_server.log && echo "[+] ping tests completed" >> analysis/raw_logs/T1/ping_server_client.log
echo "----------------------------------------------" >> analysis/raw_logs/T1/ping_server_client.log && 
echo "----------------------------------------------" >> analysis/raw_logs/T1/ping_client_server.log
#-----------------------------------------------------------------------#

#------------------------------Iperf3 server--------------------------------------#
echo "[+] Avvio iperf3 server..."
kathara exec -d $TOPOLOGY_DIR server "bash -c 'iperf3 -s > /dev/null 2>&1 &' &"

# Attendi un secondo per sicurezza
sleep 1

echo "[+] Avvio test client..."
kathara exec -d topologies/T1 clientntp "iperf3 -c $SERVER_IP -t 5" >> analysis/raw_logs/T1/iperf3_client_server.log 2>&1


echo "[+] Pulizia processi iperf3 server..."
kathara exec -d "$TOPOLOGY_DIR" server -- pkill iperf3 || true
#-----------------------------------------------------------------------#

#------------------------------Iperf3client-----------------------------------------#
echo "[+] Avvio iperf3 client..."
kathara exec -d $TOPOLOGY_DIR clientntp "bash -c 'iperf3 -s > /dev/null 2>&1 &' &"

# Attendi un secondo per sicurezza
sleep 1

echo "[+] Avvio test server..."
kathara exec -d topologies/T1 server "iperf3 -c $CLIENT_IP -t 5" >> analysis/raw_logs/T1/iperf3_server_client.log 2>&1


echo "[+] Pulizia processi iperf3 server..."
kathara exec -d "$TOPOLOGY_DIR" server -- pkill iperf3 || true
#-----------------------------------------------------------------------#

echo "[+] Tests completed, shutting down..."

#  Clean the lab
kathara lclean -d $TOPOLOGY_DIR
