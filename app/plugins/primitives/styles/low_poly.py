"""Lo stile low poly, come profilo registrabile.

Sta qui, con le primitive, perche' e' il linguaggio geometrico che quelle
primitive parlano: pochi lati, spigoli veri, niente arrotondamenti. Un altro
plugin che porti un altro stile lo dichiara per conto proprio e il core non
cambia di una riga.

`faces_per_normal` e' il numero che distingue una forma **disegnata** da una
campionata. A 1 ogni triangolo ha la sua normale: e' cio' che succede quando la
superficie viene estratta da un campo implicito e nessuno ha deciso dove
mettere gli spigoli. A 2 ci sono quadrilateri piatti, cioe' facce vere.

La soglia sta a **1,55** e non a 1,8 per un motivo misurato, non per prudenza.
Una forma fatta solo di quadrilateri vale 2; una che comprende facce
legittimamente triangolari vale meno — un tetto a due falde, che ha due timpani
triangolari su otto facce, vale 1,60. Alzare la soglia sopra quel valore
vorrebbe dire chiamare "blob" un tetto disegnato bene. Sotto 1,2 invece non ci
arriva nessuna geometria progettata: li' c'e' solo cio' che e' stato campionato.
"""
from app.core.vocabulary import StyleProfile

LOW_POLY = StyleProfile(
    id="low_poly",
    name="Low poly",
    description="poche facce, spigoli veri, tinte piatte",
    params={
        "faces_per_normal_min": 1.55,
        "triangle_budget": 3200,
        "sides": 6,
        "smoothing": 0,
        "flat_materials": True,
    },
    tags=frozenset({"cartoon", "low_poly"}),
)
