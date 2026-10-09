"""Versionsangabe des Kelvex Agent, getrennt von core/version.py (Core und Agent werden
unabhängig voneinander versioniert, auch wenn sie aus demselben Checkout ausgeliefert
werden). Core vergleicht hiergegen, um zu entscheiden, ob es einem meldenden Agenten eine
neuere Version anbietet (siehe webui/app.py und core/updater.py::is_newer())."""

__version__ = "0.2.0"
