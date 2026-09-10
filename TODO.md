# Che cosa manca

Aggiornato il 10 settembre 2026, dopo la rimozione della pipeline storica.

Lo stato: **947 test verdi**, un solo percorso dal prompt al modello, 12
plugin, API congelate. Quello che segue e' cio' che non c'e' — scritto per
essere onesto, non per essere lungo.

---

## Debiti veri

**1. L'editing a voce non c'e' piu'.** `Session.modify("fai le ruote piu'
grandi")` girava sulla pipeline storica ed e' stato tolto con lei. Oggi si
modifica il piano e si chiama `regenerate()`. Perche' torni servono due cose:
un planner che sappia **riscrivere** un piano esistente invece di scriverne uno
nuovo, e un modo di dire all'LLM che cosa c'e' gia' (il piano corrente e' gia'
JSON, quindi e' meno lavoro di quanto sembri).

**2. La generazione da un'immagine non c'e' piu'.** Stessa ragione: leggeva una
foto e produceva un `GenerationPlan`. Il pulsante nella UI e' nascosto. Serve
riscrivere `reference.py` perche' produca un piano di composizione — misure e
colore dell'immagine diventano parametri e materiali, non piu' un template.

**3. Il planner locale ragiona per parole.** Senza rete sceglie i componenti
per corrispondenza fra le parole della richiesta e nomi, tag e descrizioni. Un
plugin che dimentica i tag e' invisibile a quel planner (non all'LLM vero), e il
ripiego peggiora in silenzio. Un test lo verifica sui plugin nostri; per quelli
di altri servirebbe un avviso al caricamento.

**4. Un ginocchio non si piega.** Coscia, polpaccio e piede sono **fratelli**
appesi ai socket della gamba, non una catena: l'arto si muove rigido. E' una
conseguenza vera di come i segmenti sono composti, ed e' fissata da un test. Per
piegare un ginocchio servirebbe che un segmento si attacchi al precedente, che
e' una scelta di composizione da fare nel plugin `humanoid`.

**5. Nessuno appoggia il modello a terra, se non lo si chiede.**
`Scene.ground_offset` esiste e `to_scene(ground=True)` lo fa, ma non c'e' un
effetto `ground` nello stadio `final`: chi costruisce senza passare per la
scena ottiene il modello dove i componenti l'hanno messo.

**6. La compenetrazione si misura con scatole allineate agli assi.** Due lame
incrociate risultano sovrapposte senza toccarsi. Le soglie sono larghe apposta,
ma resta un compromesso.

---

## Cose che sarebbero utili, e non urgenti

- **Stili veri.** La struttura c'e' ed e' provata (un plugin puo' registrare
  `cartoon` che estende `low_poly` e cambia due numeri). Manca qualcuno che ne
  scriva uno completo, e finche' non succede non si sa quali numeri servano
  davvero.
- **Un plugin realistico.** Un test dimostra che il core lo reggerebbe: un
  componente con parametri, figli, vincoli e geometria completamente diversi che
  fornisce `head_mount`. Scriverlo per intero e' un'altra fase.
- **Il vocabolario cresce con i plugin.** A 44 componenti sono 16 KB (~4.100
  token). A qualche centinaio andra' filtrato prima di mandarlo a un modello:
  probabilmente per capability e per tag, a partire dalla richiesta.
- **Nessuna prova su un modello vero.** La correzione unica, il punteggio dei
  piani e lo structured output sono provati con fornitori finti. Con un modello
  vero si scoprira' quanto e' buono il riassunto delle diagnosi.

---

## Cose che non vanno fatte adesso

Marketplace, plugin store, registry remoto, esecuzione in cloud, sandbox dei
plugin, generazione automatica di plugin, cicli di correzione infiniti, giudizio
visivo affidato a un modello, IK completo, motore di collisione completo,
risolutore CAD, build distribuita, database.

Ognuna di queste, oggi, aggiungerebbe infrastruttura per un problema che non
abbiamo.
