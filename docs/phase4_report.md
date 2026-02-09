# Fase 4 - parsing/plotting

## Plot PTP – significato e utilizzo

### Boundary

#### `boundary_<scenario>_offset_ns.png`
Rappresenta l’offset temporale (in nanosecondi) tra il boundary clock e il master nel tempo.  
È utilizzato per valutare la stabilità complessiva del sincronismo, osservare il comportamento transitorio e confrontare l’impatto dei diversi scenari di rete (low, medium, high).

#### `boundary_<scenario>_offset_ns_postlock_s2.png`
Mostra l’offset temporale limitatamente alla fase di lock del servo (`s2`).  
Consente di analizzare la qualità del sincronismo a regime, separando il transitorio iniziale dal comportamento stabile. È il riferimento principale per il calcolo delle metriche statistiche (media, deviazione standard, percentili).

#### `boundary_<scenario>_path_delay_ns.png`
Rappresenta la stima del path delay end-to-end nel tempo.  
È utilizzato per valutare la variabilità del ritardo di rete e per correlare eventuali degradazioni dell’offset con instabilità introdotte da delay, jitter o loss.

---

### Client

#### `client_<scenario>_rms_ns.png`
Rappresenta l’RMS dell’offset temporale stimato dal client.  
Fornisce una misura aggregata e robusta della qualità del sincronismo ed è il principale indicatore per il confronto tra scenari di rete.

#### `client_<scenario>_path_delay_ns.png`
Mostra la stima del path delay osservata dal client, quando disponibile.  
È utilizzato per analizzare la relazione tra variabilità del ritardo di rete e degradazione dell’RMS del sincronismo.

---

## Struttura dei dati di analisi

### Samples
I `samples` contengono grandezze numeriche continue estratte dai log (offset, RMS, path delay, stato del servo), indicizzate nel tempo.  
Sono utilizzati per la generazione dei grafici time-series e per il calcolo delle statistiche a regime.

### Events
Gli `events` rappresentano eventi discreti del protocollo (transizioni di stato, fault, reselezione del master).  
Sono utilizzati per identificare il tempo di convergenza, analizzare la robustezza del protocollo e fornire tracciabilità temporale degli stati, ma non sono impiegati direttamente nei plot principali.

# NTPsec — Plot (ntpsec_analysis)

## ntpsec_boundary_<scenario>_offset_ms.png
- Serie temporale dell’**offset** stimato verso la sorgente selezionata (`*` in tabella `ntpq -p`).
- Rappresenta l’errore di sincronizzazione del nodo boundary rispetto al riferimento NTP.
- Unità: **millisecondi (ms)**.

## ntpsec_boundary_<scenario>_delay_ms.png
- Serie temporale del **delay** (ritardo di rete stimato) verso la sorgente selezionata.
- Rappresenta una stima del path/RTT nel modello NTP.
- Unità: **millisecondi (ms)**.

## ntpsec_boundary_<scenario>_jitter_ms.png
- Serie temporale del **jitter** stimato verso la sorgente selezionata.
- Rappresenta la variabilità delle misure (instabilità temporale del campionamento).
- Unità: **millisecondi (ms)**.

## ntpsec_client_<scenario>_offset_ms.png
- Come sopra, ma sul nodo client (errore di sincronizzazione del client rispetto al boundary/server selezionato).
- Unità: **millisecondi (ms)**.

## ntpsec_client_<scenario>_delay_ms.png
- Come sopra, ma sul nodo client (delay stimato verso la sorgente selezionata).
- Unità: **millisecondi (ms)**.

## ntpsec_client_<scenario>_jitter_ms.png
- Come sopra, ma sul nodo client (jitter stimato verso la sorgente selezionata).
- Unità: **millisecondi (ms)**.

# Chrony — Plot (chrony_analysis)

## chrony_<scenario>_tracking_system_time_offset_us.png
- Serie temporale dell’**offset del clock locale** rispetto al tempo NTP selezionato, derivato da `tracking -> System time`.
- Rappresenta l’errore effettivo del nodo (metrica primaria per accuratezza).
- Unità: **microsecondi (µs)**.

## chrony_<scenario>_sourcestats_stddev_us.png
- Serie temporale della **deviazione standard** delle misure verso la sorgente, derivata da `sourcestats -> Std Dev`.
- Proxy della “rumorosità”/instabilità delle misure (metrica primaria per stabilità).
- Unità: **microsecondi (µs)**.

## chrony_<scenario>_sourcestats_offset_us.png
- Serie temporale dell’**offset stimato verso la sorgente**, derivato da `sourcestats -> Offset`.
- Metrica di diagnostica sulla sorgente (non è l’errore finale del clock locale).
- Unità: **microsecondi (µs)**.


