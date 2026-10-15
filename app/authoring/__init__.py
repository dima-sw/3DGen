"""Authoring: trasformare un modello 3D in conoscenza riutilizzabile di 3DGen.

Questo pacchetto e' **la strada programmatica**, non l'interfaccia. La UI
(`app/ui/authoring_window.py`) e' un suo cliente sottile, esattamente come la
UI di generazione e' un cliente sottile di `Session`: ogni operazione di
authoring esiste come chiamata, e si puo' eseguire senza aprire una finestra.

Il motivo non e' eleganza. Un domani che decompone un concetto con un modello
(«Teach 3DGen») deve poter costruire un plugin **senza pilotare widget**, e un
tool a riga di comando o un test devono poter fare lo stesso. Se l'unico modo
di creare un componente fosse premere un bottone, quella strada andrebbe
riscritta.

    AuthoringService      le operazioni: importa, crea, aggancia, innesta,
                          dichiara, valida, salva, installa
    AuthoringProject      lo stato temporaneo del lavoro, serializzabile
    ComponentLab          qualunque componente **installato**, con i suoi
                          parametri, i suoi trait e i suoi effetti
    VariantRecipe         una configurazione utile, salvata senza duplicare
                          la geometria

Cio' che esce dal salvataggio e' un normale plugin dati V4/V5: JSON accanto a
GLB, nessun Python, nessun formato parallelo. Vedi `app/core/data_plugin.py`.
"""
from __future__ import annotations

from app.authoring.errors import AuthoringError
from app.authoring.lab import ComponentLab, LabResult, ParamKnob
from app.authoring.model import (CANDIDATE, COVERAGE, MISSING, PROXY, VALIDATED,
                                 AuthoringProject, DraftChild, DraftComponent,
                                 DraftParam, DraftSocket, SceneObject, SourceModel)
from app.authoring.service import (AuthoringService, CapabilityView, InstallResult,
                                   ValidationReport)
from app.authoring.variant import VariantRecipe

__all__ = [
    "AuthoringError", "AuthoringProject", "AuthoringService", "CANDIDATE",
    "COVERAGE", "CapabilityView", "ComponentLab", "DraftChild", "DraftComponent",
    "DraftParam", "DraftSocket", "InstallResult", "LabResult", "MISSING",
    "PROXY", "ParamKnob", "SceneObject", "SourceModel", "VALIDATED",
    "ValidationReport", "VariantRecipe",
]
