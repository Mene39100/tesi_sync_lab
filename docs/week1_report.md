#packages installed (sudo apt install kathara chrony linuxptp python3 python3-pip git -y)
KATHARA, CHRONY, LINUXPTP, PYTHON3, PYTHON3-PIP, GIT


------------------------------------------------------------------------
#kathara check
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                      System Check                                                                       │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
Current Manager is:             Docker (Kathara)
Manager version is:             28.5.1
Python version is:              3.11.13 (main, Jun  4 2025, 08:57:30) [GCC 13.3.0]
Kathara version is:             3.8.0
Operating System version is:    Linux-6.8.0-79-generic-aarch64
[Deploying devices]   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1/1
[Deleting devices]   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1/1
✓ Container run successfully.
------------------------------------------------------------------------

#Creazione topologia T1 (topologies/T1.lab) [client <-> server] (ip statico) -> topologia base due nodi [seguiranno Tn topologie differenti]

### test CLIENT → SERVER
[+] Verificato ping biderezionale (IMCP)
[+] Verificato iperf3 bidirezionale (TCP/IP)
[+] ./script/bootstrapT1.sh -> script automatizzato per file di log (verifiche precedenti)
[+] installazione pacchetti (chrony, ntp, linuxptp), dentro container topologia base T1
[+] verifica corretta installazione e funzionalità dei packages in preparazione alla fase 2
[+] creazione e disposizione file per fase 2
