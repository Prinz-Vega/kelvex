"""Erststart-/Einstellungsdialog für den Kelvex Agent: fragt nur nach der
Kelvex-Core-Adresse -- client_id wird automatisch erzeugt (siehe agent_config.py),
das Token kommt erst nach Freigabe durch den Operator im Dashboard, ist also beim
Erststart noch unbekannt und wird hier nicht abgefragt.

tkinter statt eines neuen GUI-Frameworks -- Teil der Standardbibliothek, passt zum
"reduziert, unaufdringlich"-Anspruch des Agenten (kein neues Abhängigkeits-Gewicht).

Im Kelvex-Design gehalten (dieselben Farb-Tokens wie das Toast-Popup in tray.py), statt
des generischen tkinter.simpledialog-Standarddialogs. Erwartet IMMER ein bereits
existierendes Tk-Root als Elternfenster -- NIEMALS selbst ein zweites tk.Tk() erzeugen,
während an anderer Stelle bereits eine Haupt-Event-Schleife läuft (root.mainloop() in
tray.py): zwei parallele Tcl-Interpreter in unterschiedlichen Threads führen genau zu dem
Bug, der hier behoben wurde -- ein Dialogfenster erscheint, aber Klicks werden nicht
verarbeitet, weil nur eine der beiden Event-Schleifen tatsächlich läuft.

Sprache: Englisch primär, Deutsch sekundär (siehe i18n.py, agent_config.py::language) --
der Einrichtungsdialog hat einen eigenen EN/DE-Umschalter, der die sichtbaren Texte der
Buttons/Labels sofort live aktualisiert (über tk.StringVar statt festem text=...), nicht
erst nach einem Neustart."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Optional

from PIL import Image, ImageTk

from desktop_agent.i18n import t

K_BG = "#121417"
K_SURFACE = "#1E2226"
K_BORDER = "#2A2F35"
K_TEXT = "#F5F5F5"
K_TEXT_MUT = "#8A94A0"
K_NORMAL = "#DFFF00"

_ICON_PATH = Path(__file__).resolve().parent / "agent_icon.png"
_window_icon_cache: Optional["ImageTk.PhotoImage"] = None
_about_icon_cache: Optional["ImageTk.PhotoImage"] = None


def _window_icon() -> "ImageTk.PhotoImage":
    """Titelleisten-Icon für Dialogfenster -- gecacht, da PhotoImage-Objekte sonst vom
    Python-GC eingesammelt werden könnten, sobald keine Python-Referenz mehr existiert
    (Tk selbst hält nur eine interne C-Referenz, die das nicht verhindert)."""
    global _window_icon_cache
    if _window_icon_cache is None:
        _window_icon_cache = ImageTk.PhotoImage(Image.open(_ICON_PATH))
    return _window_icon_cache


def _about_icon() -> "ImageTk.PhotoImage":
    global _about_icon_cache
    if _about_icon_cache is None:
        _about_icon_cache = ImageTk.PhotoImage(Image.open(_ICON_PATH).resize((48, 48)))
    return _about_icon_cache


def _lang_toggle_row(parent: tk.Widget, bg: str, current_lang: tk.StringVar) -> tk.Frame:
    """EN/DE-Umschalter, wiederverwendet in beiden Dialogen unten. Die gewählte Sprache
    wird aktiv hervorgehoben (Volt-Akzent), die andere bleibt gedämpft."""
    row = tk.Frame(parent, bg=bg)
    buttons: dict[str, tk.Button] = {}

    def _refresh() -> None:
        for code, btn in buttons.items():
            active = code == current_lang.get()
            btn.configure(fg=K_NORMAL if active else K_TEXT_MUT)

    def _select(code: str) -> None:
        current_lang.set(code)
        _refresh()

    for code, label in (("en", "EN"), ("de", "DE")):
        btn = tk.Button(
            row, text=label, command=lambda c=code: _select(c), bg=bg,
            activebackground=bg, relief="flat", font=("Consolas", 9, "bold"),
            borderwidth=0, padx=6,
        )
        btn.pack(side="left")
        buttons[code] = btn
    _refresh()
    return row


def ask_core_url(parent: tk.Tk, initial: str = "", lang: str = "en") -> tuple[Optional[str], str]:
    """Muss vom selben Thread aufgerufen werden, der parent.mainloop() betreibt --
    blockiert per wait_window() bis Speichern/Abbrechen/Schließen. Für den Aufruf aus
    einem anderen Thread (z.B. einem pystray-Menü-Callback) siehe
    tray.py::_ask_core_url_threadsafe(). Rückgabe: (neue_url_oder_None, gewählte_sprache)
    -- die Sprache wird IMMER zurückgegeben, auch bei Abbruch, damit ein reiner
    Sprachwechsel ohne URL-Änderung trotzdem gespeichert wird."""
    result: list[Optional[str]] = [None]
    current_lang = tk.StringVar(value=lang)

    dialog = tk.Toplevel(parent)
    dialog.title(t("window.settings_title", lang))
    dialog.iconphoto(False, _window_icon())
    dialog.configure(bg=K_SURFACE, highlightthickness=1, highlightbackground=K_BORDER)
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)

    body = tk.Frame(dialog, bg=K_SURFACE, padx=20, pady=16)
    body.pack(fill="both", expand=True)

    header_row = tk.Frame(body, bg=K_SURFACE)
    header_row.pack(fill="x", anchor="w")
    tk.Label(
        header_row, text="KELVEX AGENT", bg=K_SURFACE, fg=K_TEXT,
        font=("Consolas", 11, "bold"),
    ).pack(side="left")
    _lang_toggle_row(header_row, K_SURFACE, current_lang).pack(side="right")

    prompt_var = tk.StringVar(value=t("settings.prompt", lang))
    tk.Label(
        body, textvariable=prompt_var, bg=K_SURFACE, fg=K_TEXT_MUT, font=("Consolas", 9),
        wraplength=320, justify="left",
    ).pack(anchor="w", pady=(10, 6))

    entry_var = tk.StringVar(value=initial)
    entry = tk.Entry(
        body, textvariable=entry_var, bg=K_BG, fg=K_TEXT, insertbackground=K_TEXT,
        relief="flat", highlightthickness=1, highlightbackground=K_BORDER,
        highlightcolor=K_NORMAL, font=("Consolas", 10), width=36,
    )
    entry.pack(fill="x", ipady=4)
    entry.focus_set()
    entry.select_range(0, "end")

    button_row = tk.Frame(body, bg=K_SURFACE)
    button_row.pack(fill="x", pady=(14, 0))

    def _submit(_event=None) -> None:
        value = entry_var.get().strip().rstrip("/")
        result[0] = value or None
        dialog.destroy()

    def _cancel(_event=None) -> None:
        dialog.destroy()

    cancel_var = tk.StringVar(value=t("settings.cancel", lang))
    save_var = tk.StringVar(value=t("settings.save", lang))

    tk.Button(
        button_row, textvariable=cancel_var, command=_cancel, bg=K_SURFACE, fg=K_TEXT_MUT,
        activebackground=K_BORDER, activeforeground=K_TEXT, relief="flat",
        font=("Consolas", 9), padx=12, pady=4, highlightthickness=1,
        highlightbackground=K_BORDER,
    ).pack(side="right")
    tk.Button(
        button_row, textvariable=save_var, command=_submit, bg=K_NORMAL, fg=K_BG,
        activebackground=K_TEXT, activeforeground=K_BG, relief="flat",
        font=("Consolas", 9, "bold"), padx=12, pady=4,
    ).pack(side="right", padx=(0, 8))

    def _on_lang_change(*_args) -> None:
        active = current_lang.get()
        dialog.title(t("window.settings_title", active))
        prompt_var.set(t("settings.prompt", active))
        cancel_var.set(t("settings.cancel", active))
        save_var.set(t("settings.save", active))

    current_lang.trace_add("write", _on_lang_change)

    dialog.bind("<Return>", _submit)
    dialog.bind("<Escape>", _cancel)
    dialog.protocol("WM_DELETE_WINDOW", _cancel)

    dialog.update_idletasks()
    x = parent.winfo_screenwidth() // 2 - dialog.winfo_reqwidth() // 2
    y = parent.winfo_screenheight() // 2 - dialog.winfo_reqheight() // 2
    dialog.geometry(f"+{x}+{y}")

    # BEWUSST KEIN dialog.transient(parent): parent ist dauerhaft withdraw()n (siehe
    # tray.py) -- auf Windows hängt sich die Sichtbarkeit eines transienten Fensters an
    # sein (hier unsichtbares) Owner-Fenster, wodurch der Dialog selbst nie erscheint,
    # ohne einen sichtbaren Fehler zu werfen (pythonw.exe hat keine Konsole für
    # Tracebacks). -topmost sorgt bereits dafür, dass der Dialog über anderen Fenstern
    # bleibt, auch ohne transient-Beziehung.
    dialog.deiconify()
    dialog.lift()
    dialog.focus_force()
    try:
        dialog.grab_set()
    except tk.TclError:
        pass  # Grab fehlgeschlagen (z.B. Fenster noch nicht gemappt) -- Dialog bleibt trotzdem nutzbar, nur nicht strikt modal
    parent.wait_window(dialog)

    return result[0], current_lang.get()


def ask_otp(parent: tk.Tk, lang: str = "en", error_key: Optional[str] = None) -> Optional[str]:
    """Erststart-unabhängiges Entsperr-Fenster, das _open_settings() in tray.py VOR dem
    eigentlichen ask_core_url()-Dialog zeigt, sobald der Agent bereits einmal
    eingerichtet wurde (siehe tray.py::_verify_otp_threadsafe()). Gleiche Konventionen
    wie ask_core_url() (niemals .transient(), -topmost statt dessen, wait_window()).
    error_key zeigt optional eine Fehlermeldung an (z.B. nach einem falschen Code beim
    erneuten Öffnen) -- None = keine Meldung. Rückgabe: eingegebener Code oder None bei
    Abbruch."""
    result: list[Optional[str]] = [None]
    current_lang = tk.StringVar(value=lang)

    dialog = tk.Toplevel(parent)
    dialog.title(t("window.otp_title", lang))
    dialog.iconphoto(False, _window_icon())
    dialog.configure(bg=K_SURFACE, highlightthickness=1, highlightbackground=K_BORDER)
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)

    body = tk.Frame(dialog, bg=K_SURFACE, padx=20, pady=16)
    body.pack(fill="both", expand=True)

    header_row = tk.Frame(body, bg=K_SURFACE)
    header_row.pack(fill="x", anchor="w")
    tk.Label(
        header_row, text="KELVEX AGENT", bg=K_SURFACE, fg=K_TEXT,
        font=("Consolas", 11, "bold"),
    ).pack(side="left")
    _lang_toggle_row(header_row, K_SURFACE, current_lang).pack(side="right")

    prompt_var = tk.StringVar(value=t("otp.prompt", lang))
    tk.Label(
        body, textvariable=prompt_var, bg=K_SURFACE, fg=K_TEXT_MUT, font=("Consolas", 9),
        wraplength=320, justify="left",
    ).pack(anchor="w", pady=(10, 6))

    error_var = tk.StringVar(value=t(error_key, lang) if error_key else "")
    tk.Label(
        body, textvariable=error_var, bg=K_SURFACE, fg="#C74B3E", font=("Consolas", 9),
        wraplength=320, justify="left",
    ).pack(anchor="w", pady=(0, 6))

    entry_var = tk.StringVar(value="")
    entry = tk.Entry(
        body, textvariable=entry_var, bg=K_BG, fg=K_TEXT, insertbackground=K_TEXT,
        relief="flat", highlightthickness=1, highlightbackground=K_BORDER,
        highlightcolor=K_NORMAL, font=("Consolas", 14), width=12, justify="center",
    )
    entry.pack(ipady=4)
    entry.focus_set()

    button_row = tk.Frame(body, bg=K_SURFACE)
    button_row.pack(fill="x", pady=(14, 0))

    def _submit(_event=None) -> None:
        value = entry_var.get().strip()
        result[0] = value or None
        dialog.destroy()

    def _cancel(_event=None) -> None:
        dialog.destroy()

    cancel_var = tk.StringVar(value=t("settings.cancel", lang))
    unlock_var = tk.StringVar(value=t("otp.unlock", lang))

    tk.Button(
        button_row, textvariable=cancel_var, command=_cancel, bg=K_SURFACE, fg=K_TEXT_MUT,
        activebackground=K_BORDER, activeforeground=K_TEXT, relief="flat",
        font=("Consolas", 9), padx=12, pady=4, highlightthickness=1,
        highlightbackground=K_BORDER,
    ).pack(side="right")
    tk.Button(
        button_row, textvariable=unlock_var, command=_submit, bg=K_NORMAL, fg=K_BG,
        activebackground=K_TEXT, activeforeground=K_BG, relief="flat",
        font=("Consolas", 9, "bold"), padx=12, pady=4,
    ).pack(side="right", padx=(0, 8))

    def _on_lang_change(*_args) -> None:
        active = current_lang.get()
        dialog.title(t("window.otp_title", active))
        prompt_var.set(t("otp.prompt", active))
        cancel_var.set(t("settings.cancel", active))
        unlock_var.set(t("otp.unlock", active))
        if error_key:
            error_var.set(t(error_key, active))

    current_lang.trace_add("write", _on_lang_change)

    dialog.bind("<Return>", _submit)
    dialog.bind("<Escape>", _cancel)
    dialog.protocol("WM_DELETE_WINDOW", _cancel)

    dialog.update_idletasks()
    x = parent.winfo_screenwidth() // 2 - dialog.winfo_reqwidth() // 2
    y = parent.winfo_screenheight() // 2 - dialog.winfo_reqheight() // 2
    dialog.geometry(f"+{x}+{y}")

    # Siehe ask_core_url() weiter oben: bewusst kein transient(parent), derselbe
    # Windows-Sichtbarkeitsbug bei withdraw()ntem Owner-Fenster.
    dialog.deiconify()
    dialog.lift()
    dialog.focus_force()
    try:
        dialog.grab_set()
    except tk.TclError:
        pass
    parent.wait_window(dialog)

    return result[0]


def show_about(parent: tk.Tk, version: str, client_id: str, core_url: str, status: str, lang: str = "en") -> None:
    """Rein informativ, kein Rückgabewert -- kann daher per Fire-and-Forget über
    root.after(0, ...) aus einem pystray-Menü-Callback heraus angestoßen werden, ohne auf
    ein Ergebnis warten zu müssen (anders als ask_core_url())."""
    dialog = tk.Toplevel(parent)
    dialog.title(t("window.about_title", lang))
    dialog.iconphoto(False, _window_icon())
    dialog.configure(bg=K_SURFACE, highlightthickness=1, highlightbackground=K_BORDER)
    dialog.resizable(False, False)
    dialog.attributes("-topmost", True)

    body = tk.Frame(dialog, bg=K_SURFACE, padx=20, pady=16)
    body.pack(fill="both", expand=True)

    header = tk.Frame(body, bg=K_SURFACE)
    header.pack(fill="x", anchor="w")
    tk.Label(header, image=_about_icon(), bg=K_SURFACE).pack(side="left", padx=(0, 10))
    title_box = tk.Frame(header, bg=K_SURFACE)
    title_box.pack(side="left")
    tk.Label(
        title_box, text="KELVEX AGENT", bg=K_SURFACE, fg=K_TEXT,
        font=("Consolas", 12, "bold"),
    ).pack(anchor="w")
    tk.Label(
        title_box, text=f"v{version}", bg=K_SURFACE, fg=K_NORMAL,
        font=("Consolas", 9),
    ).pack(anchor="w")

    tk.Frame(body, bg=K_BORDER, height=1).pack(fill="x", pady=12)

    rows = [
        (t("about.status_label", lang), status),
        (t("about.core_label", lang), core_url or t("about.not_configured", lang)),
        (t("about.client_id_label", lang), client_id),
    ]
    for label_text, value_text in rows:
        row = tk.Frame(body, bg=K_SURFACE)
        row.pack(fill="x", anchor="w", pady=2)
        tk.Label(
            row, text=label_text.upper(), bg=K_SURFACE, fg=K_TEXT_MUT,
            font=("Consolas", 8), width=12, anchor="w",
        ).pack(side="left")
        tk.Label(
            row, text=value_text, bg=K_SURFACE, fg=K_TEXT,
            font=("Consolas", 9), anchor="w", wraplength=220, justify="left",
        ).pack(side="left", fill="x")

    close_row = tk.Frame(body, bg=K_SURFACE)
    close_row.pack(fill="x", pady=(14, 0))

    def _close(_event=None) -> None:
        dialog.destroy()

    tk.Button(
        close_row, text=t("about.close", lang), command=_close, bg=K_SURFACE, fg=K_TEXT_MUT,
        activebackground=K_BORDER, activeforeground=K_TEXT, relief="flat",
        font=("Consolas", 9), padx=12, pady=4, highlightthickness=1,
        highlightbackground=K_BORDER,
    ).pack(side="right")

    dialog.bind("<Return>", _close)
    dialog.bind("<Escape>", _close)
    dialog.protocol("WM_DELETE_WINDOW", _close)

    dialog.update_idletasks()
    x = parent.winfo_screenwidth() // 2 - dialog.winfo_reqwidth() // 2
    y = parent.winfo_screenheight() // 2 - dialog.winfo_reqheight() // 2
    dialog.geometry(f"+{x}+{y}")

    # Siehe ask_core_url() weiter oben: bewusst kein transient(parent), derselbe
    # Windows-Sichtbarkeitsbug bei withdraw()ntem Owner-Fenster.
    dialog.deiconify()
    dialog.lift()
    dialog.focus_force()
