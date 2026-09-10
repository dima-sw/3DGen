"""I materiali di base: i nomi che quasi ogni vocabolario finisce per usare.

Un componente scrive `material="skin"`, non `#c98a5a`. Il nome e' un
riferimento condiviso — come una capability — e la tinta e' una decisione dello
stile visivo. Qui ci sono le tinte dei nomi piu' comuni, e stanno con le
primitive perche' e' li' che vive il linguaggio geometrico di base.

Un plugin che porta un materiale nuovo lo dichiara per conto proprio: `nature`
porta `leaf`, `fantasy` porta `crystal`, e nessuno deve venire a scriverlo qui.
Chi dichiara un nome gia' preso con un colore diverso viene riferito e non
sovrascrive: un colore che cambia a seconda dell'ordine di caricamento e' il
genere di difetto che si scopre guardando il modello.

I valori sono quelli del renderer che il progetto usava gia': non sono stati
scelti adesso, sono stati **spostati** da dove erano cablati.
"""
from app.core.material import MaterialSpec

MATERIALI = [
    MaterialSpec(name="default", base_color="#b3b3b8", roughness=0.6,
                 description="quando nessuno ha detto niente"),
    MaterialSpec(name="skin", base_color="#c98a5a", roughness=0.55, metallic=0.0,
                 description="pelle, carne, cuoio chiaro"),
    MaterialSpec(name="hair", base_color="#59382a", roughness=0.7,
                 description="capelli, pelo, criniera"),
    MaterialSpec(name="eye", base_color="#14161c", roughness=0.12,
                 description="occhio: scuro e lucido"),
    MaterialSpec(name="mouth", base_color="#9e4747", roughness=0.5,
                 description="bocca, lingua, interno"),
    MaterialSpec(name="scale", base_color="#6b9e7a", roughness=0.45, metallic=0.05,
                 description="squame, pelle di rettile o di pesce"),
    MaterialSpec(name="metal", base_color="#8d949c", roughness=0.35, metallic=0.9,
                 description="metallo lavorato"),
    MaterialSpec(name="armor", base_color="#8b929b", roughness=0.32, metallic=0.85,
                 description="metallo da corazza, piu' opaco"),
    MaterialSpec(name="wood", base_color="#85603a", roughness=0.62,
                 description="legno"),
    MaterialSpec(name="rock", base_color="#736f6b", roughness=0.8,
                 description="pietra, roccia, terreno"),
    MaterialSpec(name="masonry", base_color="#ccbda3", roughness=0.72,
                 description="muratura, intonaco"),
    MaterialSpec(name="tile", base_color="#945748", roughness=0.55,
                 description="tegole, coppi"),
    MaterialSpec(name="glass", base_color="#8cb8d1", roughness=0.1, metallic=0.0,
                 opacity=0.45, description="vetro"),
    MaterialSpec(name="membrane", base_color="#9e7385", roughness=0.7,
                 description="membrana: ali, pinne, tessuti sottili"),
    MaterialSpec(name="horn", base_color="#cfc3a8", roughness=0.45,
                 description="corno, artiglio, becco"),
]
