"""Ponto de entrada principal do aplicativo.

Este módulo fornece uma camada fina que reexporta as classes e constantes
definidas em :mod:`video_editor_gui` para facilitar a importação em outros
locais (incluindo os testes unitários). Quando executado diretamente, abre a
interface gráfica.
"""

from __future__ import annotations

import sys

import video_editor_gui
from video_editor_gui import (
    VideoEditorApp,
    SUBTITLE_POSITIONS,
    CONFIG_FILE as _CONFIG_FILE,
    run_app,
    ConfigManager as _ConfigManager,
)


__all__ = [
    "ConfigManager",
    "VideoEditorApp",
    "SUBTITLE_POSITIONS",
    "CONFIG_FILE",
    "run_app",
    "print_usage",
    "start_gui",
]

# ---------------------------------------------------------------------------
# Reexports and helpers

# Config file path used by ConfigManager.  Exposed so tests can monkeypatch it.
CONFIG_FILE = _CONFIG_FILE


class ConfigManager:
    """Wrapper que garante o uso do ``CONFIG_FILE`` deste módulo."""

    @staticmethod
    def load_config() -> dict:
        global CONFIG_FILE
        # Mantém o módulo de origem sincronizado
        video_editor_gui.CONFIG_FILE = CONFIG_FILE
        return _ConfigManager.load_config()

    @staticmethod
    def save_config(config: dict) -> None:
        global CONFIG_FILE
        video_editor_gui.CONFIG_FILE = CONFIG_FILE
        _ConfigManager.save_config(config)


def print_usage() -> None:
    """Exibe instruções de uso básicas."""
    print("Uso: python main.py [--help]")
    print("Sem argumentos, abre a interface gráfica do editor.")


def start_gui() -> None:
    """Inicializa a aplicação gráfica."""
    run_app()


if "--help" in sys.argv or "-h" in sys.argv:
    print_usage()
else:
    if __name__ == "__main__":
        start_gui()
