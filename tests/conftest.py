"""Fixture condivise dai test di Teach 3DGen.

Una sola, e serve a due cose: non costruire un `TeachService` a mano in ogni
test, e **non lasciare cartelle di staging in giro**. Il servizio tiene i file
generati sotto una radice che `close()` cancella; qui la radice e' quella di
`tmp_path`, cosi' pytest la pulisce comunque.

Il provider e' sempre `OfflineProvider`: nessun test di questa milestone tocca
la rete, e un provider configurato sulla macchina di chi esegue i test non deve
cambiare il risultato. La modalita' esterna di §5 non e' un ripiego, quindi i
test la usano come strada normale.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def teach_session():
    """Una `Session` con la libreria installata e nessun provider remoto."""
    from app.ai.provider import OfflineProvider
    from app.core.session import Session

    return Session(provider=OfflineProvider())


@pytest.fixture
def teach(tmp_path, teach_session):
    """Un `TeachService` con lo staging sotto `tmp_path`."""
    from app.teach import TeachService
    from app.teach.knowledge import TeachKnowledge

    service = TeachService(session=teach_session,
                           knowledge=TeachKnowledge(),
                           staging_root=tmp_path / "teach-staging")
    try:
        yield service
    finally:
        service.close()
