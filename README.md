# Tokenzähler

Wertet die lokalen Claude-Code-Protokolle (`~/.claude/projects/**/*.jsonl`) aus. Gezählt wird für die letzten 7 Tage, aufgeteilt nach Projekt, Sitzung und Agent (Hauptsitzung oder Subagent mit Typ, Aufgabe und Modell). Die Tokens rechnet das Tool mit `preise.json` in Euro um. Das ergibt den Gegenwert zu API-Preisen, nicht die tatsächlichen Abo-Kosten.

## Nutzung
- `python3 tokenzaehler.py`: Tabelle im Terminal
- `python3 tokenzaehler.py --html`: schreibt `bericht.html` (ein Klick auf ein Projekt klappt seine Agenten auf)
- `python3 tokenzaehler.py --json`: liefert die Daten für die Menüleisten-App
- `--tage N`: ändert das Fenster
- Menüleiste: `sh app/build.sh`, danach `open app/Tokenzaehler.app`. Die App aktualisiert sich alle 5 Minuten und beim Öffnen, wenn der Stand älter als 1 Minute ist.
- Panel (Dashboard): Limitbalken (grün < 60 %, orange < 85 %, sonst rot; inaktive Limits grau), Gesamtwerte, Top-5-Projekte mit Balken. Weitere Projekte und die Agenten eines Projekts (Top 5) klappen per Klick auf.

## Regeln
- Projekt: Unterordner von `~/Claude/` laut `cwd`. Liegt `cwd` in einem temporären Ordner, steht dort „(temporär)“.
- Doppelte Einträge: Gleiche `message.id` und `requestId` zählen einmal, und zwar der letzte Eintrag (bei Streaming wächst er kumulativ). So macht es auch CodexBar.
- Tokens: Input, Output, Cache-Schreiben und Cache-Lesen werden addiert. Cache-Preise: 5-Minuten-Schreiben 1,25×, 1-Stunden-Schreiben 2× und Lesen 0,1× des Input-Preises.

## Vorbild
CodexBar von Peter Steinberger (github.com/steipete/CodexBar, MIT). Es zeigt die offiziellen Prozentwerte für das 5-Stunden- und das Wochenlimit über den OAuth-Usage-Endpoint und Kosten pro Projekt. Subagents schlüsselt es aber nicht auf. Genau diese Lücke füllt dieses Tool.
