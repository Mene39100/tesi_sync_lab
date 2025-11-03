#!/bin/bash
source ./scripts/envT2.sh

echo "[+] Disattivo eth1 in tutti i nodi (post-start)"
for node in servergm serverntp clientchrony clientntp clientptp; do
  if kathara exec -d "$TOPOLOGY_DIR" "$node" 'ip link set eth1 down' >/dev/null 2>&1; then
    echo "[+] eth1 disattivata in $node"
  else
    echo "[!] eth1 non presente in $node"
  fi
done
if kathara exec -d "$TOPOLOGY_DIR" boundary 'ip link set eth2 down' >/dev/null 2>&1; then
    echo "[+] eth2 disattivata in boundary"
  else
    echo "[!] eth2 non presente in boundary"
  fi
echo "[✓] Connessione Internet disattivata in tutti i nodi."