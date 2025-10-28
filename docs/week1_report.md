### Packages installed 
- (sudo apt install kathara chrony linuxptp python3 python3-pip git -y)
- KATHARA, CHRONY, LINUXPTP, PYTHON3, PYTHON3-PIP, GIT

------------------------------------------------------------------------
### Kathara check
System check
Current Manager is: Docker (Kathara)
Manager version is: 28.5.1
Python version is: 3.11.13 (main, Jun  4 2025, 08:57:30) [GCC 13.3.0]
Kathara version is: 3.8.0
Operating System version is: Linux-6.8.0-79-generic-aarch64
✓ Container run successfully.
------------------------------------------------------------------------

Creazione topologia T1 (topologies/T1.lab) [client <-> server] (ip statico) -> topologia base due nodi [seguiranno Tn topologie differenti]

### test CLIENT → SERVER
[+] Verificato ping biderezionale (IMCP)

[+] Verificato iperf3 bidirezionale (TCP/IP)

[+] ./script/bootstrapT1.sh -> script automatizzato per file di log (verifiche precedenti)

[+] installazione pacchetti (chrony, ntp, linuxptp), dentro container topologia base T1

[+] verifica corretta installazione e funzionalità dei packages in preparazione alla fase 2

[+] creazione e disposizione file per fase 2

[+] creazione doppio client (NTP e Chrony) -> Nel primo scenario si confrontano due implementazioni dello stesso protocollo (NTPv4): una classica (ntpsec) e una moderna (chrony), valutandone la precisione e il tempo di convergenza in una rete simulata Kathará. Lo scopo è verificare l’efficacia degli algoritmi di clock discipline e di compensazione del jitter di rete.

[+] ClientPTP con installazione solo di linuxptpt

------------------------------------------------------------------------

### Riassunto Week 1

In questa prima fase del progetto è stata impostata l’intera infrastruttura di base necessaria per l’ambiente di simulazione dedicato alla sincronizzazione temporale.  
Sono state organizzate le directory generali del laboratorio, strutturandole in modo ordinato con le principali sottocartelle: `topologies/`, `scripts/`, `configs/`, `analysis/` e `docs/`.  
All’interno della cartella `topologies/`, predisposta a contenere le diverse topologie di rete, è stata creata la prima denominata *T1*, che rappresenta lo scenario base composto da un server e due client distinti, `clientNTP` e `clientChrony`, al fine di poter testare protocolli differenti in parallelo.  
Ogni nodo all’interno della topologia dispone di un proprio file `.startup`, che contiene le istruzioni di configurazione eseguite automaticamente al momento dell’avvio del container.

All’interno di ciascun file `.startup` è stato configurato manualmente l’indirizzo IP statico corrispondente (`10.0.0.x/24`), assegnato all’interfaccia di rete, e l’interfaccia è stata successivamente abilitata tramite i comandi `ip addr add` e `ip link set`.  
È stato inoltre impostato il *DNS pubblico 8.8.8.8* (quello di Google) all’interno del file `/etc/resolv.conf`, permettendo la risoluzione dei domini necessari al download dei pacchetti.  
Questa operazione garantisce la connessione esterna dei container alle repository Debian.

Successivamente, per consentire la corretta gestione dei pacchetti, sono state aggiunte nei file `.startup` le sezioni di configurazione dei *repository ufficiali Debian*, sostituendo eventuali fonti obsolete.  
Dopo l’aggiornamento delle sorgenti (`apt update`), sono stati installati i pacchetti fondamentali per la sincronizzazione temporale. In particolare:

- Nei client NTP e Chrony sono stati installati rispettivamente `ntpsec` e `chrony`, insieme a `linuxptp`, necessario per il protocollo PTP.  
- Nel server è stata predisposta un’installazione duale con `chrony` e `linuxptp`, in modo da poterlo utilizzare sia come master NTP/Chrony sia come Grandmaster PTP.

Parallelamente alla configurazione dei singoli nodi, è stato creato e configurato il file `lab.conf`, che descrive la topologia di rete e le relazioni tra i dispositivi.  
In questo file sono state definite le interconnessioni tra server e client, specificando la collision domain (identificata come `A`), e abilitata la modalità `bridged=true` per permettere ai nodi di accedere a Internet e scaricare le dipendenze durante l’avvio.

Terminata la parte di configurazione di rete, sono stati realizzati gli script di automazione nella cartella `scripts/`. In particolare:

- Il file `bootstrapT1.sh` esegue in modo automatico la creazione e la distruzione della topologia (`lstart`, `lclean`), effettua test di *ping* e *iperf3* tra server e `clientChrony` (scelto arbitrariamente tra i due) per verificare la connettività e le prestazioni, e salva tutti i risultati di log nella cartella `analysis/raw_logs/`.  
- Il file `env.sh` definisce variabili d’ambiente utili ai test, come indirizzi IP e percorsi di log, centralizzando i riferimenti per rendere gli script più modulari e riutilizzabili.

Infine, è stata predisposta la cartella `configs/`, che conterrà la configurazione specifica dei protocolli di sincronizzazione temporale.  
In essa sono state create tre sottocartelle (`chrony/`, `ntp/`, `ptp/`) e i rispettivi file di configurazione (`client_chrony.conf`, `server_chrony.conf`, `client_ntp.conf`, `server_ntp.conf`, `client_ptp.conf`, `server_ptp.conf`), che verranno completati nelle fasi successive.  
Questa separazione strutturale tra topologia, script e configurazione consente di mantenere una chiara distinzione tra la logica di rete e la logica applicativa di sincronizzazione.

In sintesi, la *Fase 1* si è conclusa con la realizzazione di un’infrastruttura Kathará completamente automatizzabile, composta da più nodi con indirizzi statici, accesso a Internet, installazione automatica dei pacchetti necessari e strumenti di test di rete già integrati.
