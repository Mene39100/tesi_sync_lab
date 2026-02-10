# Progetto Tesi

## Descrizione
Questo progetto rappresenta la parte sperimentale della tesi. 
L’obiettivo principale è sviluppare un prototipo per analizzare l’impatto della sincronizzazione temporale (**NTP/PTP**).

L’analisi è condotta in ambiente "containers Docker" privo di accesso al clock hardware; pertanto, i protocolli non disciplinano il tempo di sistema ma operano come stimatori logici di offset e delay. Le metriche analizzate riflettono la qualità della sincronizzazione stimata e la robustezza del protocollo, non la correzione fisica del clock.
---

## Struttura del progetto

### 🔹 Phase 1 — Setup ambiente e topologie
- Installazione e configurazione di **Kathará** con topologie base (T1, T2).
- Configurazione nodi virtuali con pacchetti **linuxptp**, **NTP/Chrony**.
- Creazione di repository Git con file di configurazione e script di bootstrap.  

---

### 🔹 Phase 2 — Implementazione NTP & PTP
- Configurazione di **NTP** (Chrony/ntpd) in modalità server/client e raccolta offset.
- Implementazione **PTP** con ruoli Grandmaster, Slave e Boundary Clock (ptp4l, phc2sys).
- Verifica timestamping software in ambienti virtualizzati.  

---

### 🔹 Phase 3 — Scenari semi-realistici con disturbi
- Introduzione di **jitter**, delay variabili e asimmetrici tramite `tc/netem`.
- Simulazione di perdita pacchetti, riordino e congestione con **iperf3**.
- Raccolta log per scenari multipli parametrizzati (Low, Medium, High jitter).

---

### 🔹 Phase 4 — Raccolta & analisi dati
- Parsing log **PTP** (ptp4l, phc2sys) e **NTP** (chronyc) con script Python.
- Calcolo metriche: offset medio, deviazione standard, P95/P99, tempo di lock.
- Generazione grafici (CDF, boxplot) e tabelle comparative **NTP vs PTP**.  

---

### 🔹 Implementato nella Phase 3
- Demo client-server in **Bash** con eventi timestamp.
- Modalità:
  - **Sync-ON** (NTP/PTP attivi)
  - **Sync-OFF** (clock disallineati)
- Metriche: miss rate su deadline (5–20 ms), errori di ordinamento eventi, drift percepito.  

---

### 🔹 Svolto nelle Phases (1/2/3/4)
- Stesura documentazione tecnica e allegati (configurazioni, grafici, tabelle).  

---
