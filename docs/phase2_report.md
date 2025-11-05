# Fase 2 — Topologia T2, sincronizzazione multilivello e automazione dei test

## Obiettivo
In questa seconda fase è stata sviluppata e testata una topologia di rete più complessa (denominata **T2**) per la simulazione di meccanismi di sincronizzazione multilivello.  
L’obiettivo è stato realizzare un sistema in cui coesistono e vengono confrontati:
- **PTP (Precision Time Protocol)** con struttura gerarchica Grandmaster–Boundary–Slave,
- **NTPsec** e **Chrony** come protocolli NTP, eseguiti su rami separati della rete,
- un’infrastruttura di **automazione completa** per avvio, configurazione e raccolta log all’interno di container Kathará.
- Per motivi di configurazione è stato deciso a tempo di configurazione di dividere il dominio principlae (server), in due separati, il primo (*servergm*) dedicato interamente a chrony e linuxptp e il secondo (*serverntp*) solamente a ntpsec. (le motivazioni si riconducono a conflitti di installazione e permessi tra chronu e ntpsec sullo stesso container)

---

## Architettura logica e rete
La topologia T2 è composta da due domini Ethernet distinti:
- **Rete A** (`10.0.10.0/24`): dominio principale, dove risiedono `servergm` (Grandmaster PTP e chrony), `serverntp` (server NTPsec), `boundary` (eth0) e `clientchrony`.
- **Rete B** (`10.0.20.0/24`): dominio secondario, dove si trovano `boundary` (eth1), `clientptp` e `clientntp`.

Il **Boundary Clock** rappresenta il punto di interconnessione tra le due reti e svolge doppia funzione:
- come *slave PTP* rispetto al Grandmaster,
- come *master PTP* verso la rete B,
- e, opzionalmente, come bridge NTP quando vengono attivati i test misti (non contemporaneamente a PTP per evitare problematiche di sincornizzazione e diritti sul clock).

Tutti i nodi condividono un volume locale per l’accesso ai file di configurazione e ai log.  
I tutti i container (per convenienza) sono avviati con le capability `SYS_TIME`, `NET_RAW`, `NET_ADMIN` per poter modificare il clock di sistema e catturare i timestamp di rete.

---

## Descrizione operativa

### 1. Configurazione PTP
Il protocollo PTP è stato distribuito su tre livelli:
- **Grandmaster (`servergm`)**: sorgente di riferimento assoluto del tempo.
- **Boundary Clock (`boundary`)**: nodo intermedio che riceve i messaggi dal GM, calcola il proprio offset e rigenera i pacchetti verso la rete B.
- **Client PTP (`clientptp`)**: nodo finale che si sincronizza con il Boundary.

Tutti i file di configurazione (server, boundary, client) sono stati creati in `/configs/ptp/` e prevedono un dominio comune (numero 24), modalità *E2E* e timestamp software. 
Le priorità e i timeout sono stati tarati per garantire che il Grandmaster prevalesse sempre nei processi BMCA e che la rete si stabilizzasse rapidamente.
Lavorando con container Docker l'utilizzo del timestamp software è stato obbligato perdendone in qualità di precisione (non è stato possibile operare per struttura con una precisione a livello hardware), tuttavia i confronti sono stati possibili e con le dovute accortezze analizzati.

### 2. Configurazione Chrony e NTPsec
Parallelamente, sulla rete A è stato configurato **Chrony**, con `servergm` come sorgente e `clientchrony` come nodo di verifica.  
Sulla rete B, invece, è stato predisposto **NTPsec**, con `serverntp` e `clientntp`, oltre alla possibilità di utilizzare il Boundary come intermediario.  
Durante questa fase 2 il demone NTP del Boundary è rimasto disattivato, per isolare i test PTP e prevenire conflitti sul clock locale. Nel momento del test del protocollo ntp con il rispettivo demone, ovviamente, è stato riattivato e disattivato la procedura di sincronizzazione PTP.

### 3. Automazione e script di test
Tutti i test vengono eseguiti tramite uno script Bash (`bootstrapT2.sh`) che:
1. Avvia e pulisce la topologia con `kathara lstart --privileged`.
2. Rimuove la connettività esterna per garantire isolamento temporale (script secondario endInternetConnection.sh) (vengno messi in DOWN solo dopo aver permesso di installare le corrette dipendenze sui rispettivi container in fase di avvio).
3. Verifica la raggiungibilità tra i nodi chiave.
4. Avvia i demoni PTP in sequenza (Grandmaster → Boundary → Client).
5. Attende la stabilizzazione del dominio.
6. Esegue le interrogazioni `chronyc` e `ntpq` per i rami NTP.
7. Salva automaticamente tutti i log nella directory `analysis/raw_logs/T2/`.

---

## Risultati sperimentali

### 1. Dominio PTP
Il comportamento del dominio PTP rispecchia pienamente la gerarchia prevista:
- Il **Grandmaster** viene eletto come miglior clock e resta costantemente in stato *MASTER*.  
- Il **Boundary Clock** passa da *LISTENING* a *SLAVE*, calcola offset e ritardo medio, e successivamente rigenera i pacchetti come *MASTER* sulla rete B.  
- Il **Client PTP** riconosce correttamente il boundary come sorgente, raggiunge lo stato *SLAVE* e inizia a registrare cicli regolari di correzione del clock.

I log mostrano una prima fase di oscillazioni ampie (offset fino a centinaia di microsecondi) seguita da una progressiva riduzione delle deviazioni e un percorso stabile di sincronizzazione.  
Il Boundary presenta cicli di compensazione evidenti (offset, freq, path delay) mentre il Client, pur ricevendo correttamente i messaggi Sync/Follow_Up e DelayReq/Resp, tende a loggare in modo meno verboso, tipico degli slave software.

La latenza media calcolata si stabilizza nell’ordine dei **200–400 µs**, con frequenze di compensazione intorno a +70 kHz, compatibili con la precisione software del protocollo.

Come precedentemente specificato, l'impossibilità di utilizzare un timestamp di tipo hardware peggiora di almeno un ordine di misura la precisione di stabilizzazione e sincronizzazione (a tempo debito verranno fatte le oportune analisi in merito).
---

### 2. Chrony
Nel ramo A, Chrony ha mostrato un comportamento estremamente stabile:
- offset dell’ordine di **40–50 µs** rispetto al Grandmaster,
- frequenza di correzione contenuta (+86 ppm),
- root delay inferiore a 1 ms,
- stratum 9 derivato dallo stratum 8 del servergm.

I log evidenziano un’unica sorgente attiva e raggiungibilità costante, senza fasi di riacquisizione.  
Chrony si conferma quindi adatto come baseline di riferimento per valutare la precisione complessiva della rete.

---

### 3. NTPsec
Nei test NTP, condotti in parallelo, la sincronizzazione tra `serverntp` e `boundary` richiede alcuni minuti per stabilizzarsi, con oscillazioni iniziali visibili su offset e delay.  
Il client NTP in rete B rimane per un certo periodo in stato `.INIT.`, poi converge verso lo stato stabile con offset intorno a **5–10 ms** e jitter residuo sotto i 30 ms.  
Questi valori, pur inferiori alla precisione di PTP, sono coerenti con il comportamento atteso del protocollo NTP su LAN.

---

## Analisi complessiva
| Protocollo | Offset medio | Tempo di convergenza | Stabilità | Note |
|-------------|--------------|----------------------|------------|------|
| **PTP (Grandmaster → Boundary → Client)** | 0.2–0.4 ms | 5–7 s | medio-alta | Ottima precisione, oscillazioni SW |
| **Chrony** | 0.05 ms | < 1 s | alta | Sincronizzazione molto fine |
| **NTPsec** | 5–10 ms | ~ 2 minuti | alta | Robustezza, ma minore granularità |

Il dominio PTP garantisce la precisione più elevata, mentre Chrony offre un comportamento stabile e privo di variazioni rilevanti.  
NTPsec, pur meno preciso, completa il quadro come soluzione di riferimento compatibile con infrastrutture legacy.

---

## Considerazioni tecniche
- La sincronizzazione **PTP multilivello** funziona correttamente: BMCA elegge sempre il Grandmaster, il Boundary svolge un ruolo attivo di rigenerazione e il Client mantiene un tracking stabile.  
- Le capacità abilitate (`SYS_TIME`, `NET_ADMIN`, `NET_RAW`) si sono rivelate indispensabili per evitare errori di accesso ai timestamp.  
- L’avvio in modalità `--privileged` assicura coerenza di comportamento fra host e container.  
- L’automazione tramite script consente riproducibilità totale: l’intera rete viene configurata, testata e spenta senza intervento manuale.  
- La comparsa episodica del messaggio *“foreign master not using PTP timescale”* è fisiologica durante la convergenza iniziale e non influisce sulla sincronizzazione finale.

---

## Criticità riscontrate
1. **Rumore temporale software**: i container non dispongono di timestamp hardware, causando spike occasionali nei valori di offset.  
   → Mitigabile estendendo i timeout e regolando le costanti PI del servo.
2. **PMC non sempre accessibile**: il tool di management non riceve risposte se `ptp4l` non è avviato con socket UDS esplicito.  
   → Risolvibile avviando con opzione `-2` o specificando il path del socket.  
3. **Ritardo NTPsec in bootstrap**: i demoni necessitano più cicli di polling prima di convergere.  
   → Possibile miglioramento pre-generando i file di drift e riducendo l’intervallo di polling iniziale.

---

## Conclusioni
La Fase 2 ha portato alla realizzazione di un’infrastruttura di sincronizzazione **multilivello e pienamente automatizzata**, dove PTP, NTPsec e Chrony convivono in topologie separate ma interoperabili (con gli opportuni accorgimenti).  
La catena PTP Grandmaster → Boundary → Client risulta stabile e precisa, con latenza media sub-millisecondo.  
Chrony mostra prestazioni ottimali sul ramo NTP, mentre NTPsec raggiunge offset inferiori ai 10 ms dopo il periodo di inizializzazione.

Questa architettura costituisce la base per la **Fase 3**, dedicata al confronto prestazionale e alla valutazione statistica dei protocolli nel tempo, con analisi di jitter, stabilità e robustezza su run prolungati.
