"""Öffentlicher Ed25519-Schlüssel zur Lizenzverifikation -- Gegenstück zum privaten
Signierschlüssel unter deploy/keys/license_signing_key (gitignored, verlässt den
Entwickler-Rechner nie, wird niemals committed).

Bewusst im öffentlichen Quellcode eingebettet: Core muss Lizenzen VOLLSTÄNDIG offline
prüfen können (siehe verifier.py), ohne Lizenzserver und ohne Netzwerkaufruf. Das
Einbetten des PUBLIC Keys ist unproblematisch, weil er NUR Signaturen prüfen, nicht
erzeugen kann -- anders als bei einem symmetrischen Verfahren (z.B. HMAC), bei dem
derselbe Schlüssel signiert UND prüft: würde man DEN einbetten, könnte sich jeder mit
Zugriff auf den (öffentlichen!) Quellcode selbst beliebige gültige Lizenzen fälschen.
Mit Ed25519 ist das nicht möglich, da Signieren und Prüfen kryptografisch getrennte
Operationen mit unterschiedlichen Schlüsseln sind.

Wird von deploy/license_tool.py::generate-keypair befüllt (siehe dort) -- bis dahin
bewusst ein ungültiger Platzhalter, der beim Prüfversuch sofort auffällt, statt
stillschweigend "funktionierenden", aber falschen Code zu haben."""

LICENSE_PUBLIC_KEY_HEX = "0253e5cc9fedc6a285c07c1e8d8adb7fc5ef23f230f6bfc2f985435339504bff"
