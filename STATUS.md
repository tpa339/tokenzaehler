# Status · tokenzaehler
Zustand: aktiv
Aktualisiert: 2026-11-16

## Nächster Schritt
Nach dem nächsten Neustart prüfen, ob die App von selbst in der Menüleiste erscheint (Autostart).

## Zuletzt
- 2026-11-16: Menü zum Dashboard-Panel umgebaut (Limitbalken, Kennzahlen, Top-5-Projekte, Rest aufklappbar) nach Skill `design-taste-frontend` (app-screens)
- 2026-11-16: offizielle Preise (Stand 16.11.), EZB-Kurs, Effort-Aufschlüsselung, Limitabfrage über den Schlüsselbund, Autostart
- 2026-11-16: Zähler (`tokenzaehler.py`), HTML-Bericht und Menüleisten-App (`app/`) gebaut und gestartet

## To-dos
- [x] Preise geprüft (platform.claude.com/docs/en/about-claude/pricing)
- [x] Autostart (SMAppService, schaltbar im Menü)

## Entscheidungen
- [x] Limitstand anzeigen → ja, über den Claude-Login im Schlüsselbund (nur lesen, das Token wird nie gespeichert)
- [x] Fenster → rollierend letzte 7 Tage
- [x] Euro-Kurs → fest 0,86 (in preise.json)
