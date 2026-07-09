"""Tests para el almacén de sesiones."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from orik import config, session_store


@pytest.fixture
def tmp_sessions(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "SESSIONS_DIR", tmp_path / "sessions")
    return tmp_path / "sessions"


def test_new_session_id_es_unico():
    ids = {session_store.new_session_id() for _ in range(100)}
    assert len(ids) == 100


def test_load_history_inexistente(tmp_sessions):
    assert session_store.load_history("no-existe") == []


def test_save_y_load(tmp_sessions):
    sid = session_store.new_session_id()
    hist = [{"role": "user", "content": "hola"},
            {"role": "assistant", "content": "buenas"}]
    session_store.save_history(sid, hist)
    assert session_store.load_history(sid) == hist


def test_clear_history(tmp_sessions):
    sid = session_store.new_session_id()
    session_store.save_history(sid, [{"role": "user", "content": "x"}])
    session_store.clear_history(sid)
    assert session_store.load_history(sid) == []


def test_sid_vacio_es_no_op(tmp_sessions):
    session_store.save_history("", [{"role": "user", "content": "x"}])
    session_store.clear_history("")
    assert session_store.load_history("") == []


def test_cleanup_solo_borra_antiguos(tmp_sessions):
    sid_viejo = session_store.new_session_id()
    sid_nuevo = session_store.new_session_id()
    session_store.save_history(sid_viejo, [{"role": "user", "content": "viejo"}])
    session_store.save_history(sid_nuevo, [{"role": "user", "content": "nuevo"}])
    # Envejecer artificialmente el archivo viejo (60 días atrás)
    viejo_path = tmp_sessions / f"{sid_viejo}.json"
    hace_mucho = time.time() - 60 * 86400
    import os
    os.utime(viejo_path, (hace_mucho, hace_mucho))
    session_store.cleanup_old_sessions()
    assert not viejo_path.exists()
    assert (tmp_sessions / f"{sid_nuevo}.json").exists()
