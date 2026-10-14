"""Un componente procedurale che dichiara i ruoli semantici di V5.

Esiste per una misura sola, e la misura e' il punto piu' importante di V5: lo
**stesso** trait semantico deve colpire un parametro di un componente
procedurale e un parametro di un componente GLB, quando entrambi dichiarano lo
stesso `semantic_role`. Senza un componente procedurale che dichiari `width`,
quel confronto non si potrebbe fare sulla libreria installata, dove i ruoli
dichiarati sono `length` e `girth`.

La geometria viene dal kernel poligonale, come in qualunque plugin di codice:
nessuna mesh importata, nessun percorso speciale. `curve` e' un parametro che
pilota un effetto installato, per mostrare che `ParamEffect` non e' una cosa
dei plugin dati — e' una cosa dei componenti.
"""
from app.core.authoring import base_socket
from app.core.capability import Capability, mount
from app.core.component import Component, Piece
from app.core.params import DISTANCE, FLOAT, ParamSpec
from app.core.socket import socket
from app.core.vocabulary import ParamEffect
from app.geometry.kernel import block


def _testa(v, ctx) -> Piece:
    largo, alto, lungo = v["width"], v["height"], v["length"]
    mesh = block((largo, alto, lungo))
    mesh.apply_translation([0.0, alto * 0.5, 0.0])
    return Piece(mesh=mesh, material="default", tags=("probe", "head"), sockets={
        "base": base_socket(largo * 0.4, axis="+Y"),
        "tip": socket("tip", (0, alto, 0), (0, 1, 0), up=(0, 0, 1),
                      radius=largo * 0.3, provides="probe_head_mount"),
        # messo **esattamente** su un vertice del blocco: e' il modo di
        # misurare che una deformazione muove geometria e innesti con la
        # stessa mappa invece di crederci.
        "corner": socket("corner", (0, alto, lungo * 0.5), (0, 0, 1),
                         up=(0, 1, 0), radius=largo * 0.2, provides="anchor"),
    })


PROBE_HEAD = Component(
    id="head", build=_testa,
    description="a procedural probe head declaring width, height and length",
    params={
        "width": ParamSpec(0.30, DISTANCE, min=0.02, max=4.0,
                           semantic_role="width"),
        "height": ParamSpec(0.40, DISTANCE, min=0.02, max=4.0,
                            semantic_role="height"),
        "length": ParamSpec(0.25, DISTANCE, min=0.02, max=4.0,
                            semantic_role="length"),
        "curve": ParamSpec(0.0, FLOAT, min=-1.0, max=1.0,
                           semantic_role="curvature",
                           description="how curved the part is"),
    },
    param_effects=(ParamEffect(param="curve", type="fx:bend", parameter="amount",
                               scope="part", neutral=0.0),),
    provides=(Capability("head_mount"),),
    mounts=(mount("probe_head_mount", socket_id="tip"),),
    role="head", material="default",
    frame={"growth_axis": "+Y", "front": "+Z", "up": "+Y"},
    tags=frozenset({"probe", "head"}))
