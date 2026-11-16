#!/usr/bin/env python3
"""Tokenzähler: wertet lokale Claude-Code-Protokolle (~/.claude/projects) aus.

Zählt Tokens im 7-Tage-Fenster pro Projekt, Sitzung und Agent und rechnet sie
mit den Preisen aus preise.json in Euro um (API-Gegenwert, nicht Abo-Kosten).

  python3 tokenzaehler.py            Tabelle im Terminal
  python3 tokenzaehler.py --json     JSON (für die Menüleiste)
  python3 tokenzaehler.py --html     HTML-Bericht schreiben, Pfad ausgeben
  --tage N                           Fenstergröße (Standard 7)
"""
import argparse, glob, html, json, os, sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

HIER = os.path.dirname(os.path.abspath(__file__))
PROJEKTE = os.path.expanduser("~/.claude/projects")
CLAUDE_ROOT = os.path.expanduser("~/Claude") + "/"


def lade_preise():
    with open(os.path.join(HIER, "preise.json")) as f:
        lade_preise.cache = json.load(f)
    return lade_preise.cache


def preis_fuer(model, p):
    m = (model or "").lower()
    treffer = [k for k in p["modelle"] if k in m]
    return p["modelle"][max(treffer, key=len)] if treffer else None


def familie(model):  # nur noch: hat das Modell einen Preis?
    return preis_fuer(model, lade_preise.cache) is not None


def kosten_eur(u, model, p):
    pr = preis_fuer(model, p)
    if not pr:
        return 0.0
    g = lambda k: u.get(k, 0) or 0
    cc = u.get("cache_creation") or {}
    w1h = cc.get("ephemeral_1h_input_tokens", 0) or 0
    w5m = g("cache_creation_input_tokens") - w1h
    if "lang_ab" in pr and g("input_tokens") + g("cache_creation_input_tokens") + g("cache_read_input_tokens") > pr["lang_ab"]:
        pr = pr["lang"]
    usd = (g("input_tokens") * pr["in"] + w5m * pr["cw5"] + w1h * pr["cw1h"]
           + g("cache_read_input_tokens") * pr["cr"] + g("output_tokens") * pr["out"]) / 1e6
    if u.get("speed") == "fast":
        usd *= p.get("fast_faktor", 2.0)
    if u.get("inference_geo") == "us":
        usd *= p.get("geo_us_faktor", 1.1)
    return usd * p["usd_eur"]


def projektname(cwd, ordner):
    if cwd:
        if cwd.startswith(CLAUDE_ROOT):
            return cwd[len(CLAUDE_ROOT):].split("/")[0]
        if "/claude-501/" in cwd or cwd.startswith(("/tmp", "/private")):
            return "(temporär)"
        return os.path.basename(cwd.rstrip("/")) or cwd
    return ordner


def neu_summe():
    return {"input": 0, "output": 0, "cache_schreiben": 0, "cache_lesen": 0,
            "eur": 0.0, "anfragen": 0}


def addiere(s, u, eur):
    s["input"] += u.get("input_tokens", 0) or 0
    s["output"] += u.get("output_tokens", 0) or 0
    s["cache_schreiben"] += u.get("cache_creation_input_tokens", 0) or 0
    s["cache_lesen"] += u.get("cache_read_input_tokens", 0) or 0
    s["eur"] += eur
    s["anfragen"] += 1


def total(s):
    return s["input"] + s["output"] + s["cache_schreiben"] + s["cache_lesen"]


def offizielle_limits():
    """Liest den Claude-Code-Login aus dem Schlüsselbund und fragt den Limitstand ab.
    Das Token wird nur im Speicher gehalten, nie ausgegeben oder gespeichert."""
    import subprocess, urllib.request
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                           capture_output=True, text=True, timeout=20)
        if r.returncode:
            return {"fehler": "Kein Claude-Login im Schlüsselbund"}
        tok = json.loads(r.stdout)["claudeAiOauth"]["accessToken"]
        req = urllib.request.Request("https://api.anthropic.com/api/oauth/usage", headers={
            "Authorization": "Bearer " + tok, "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "tokenzaehler"})
        d = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception as e:
        code = getattr(e, "code", None)
        if code == 401:
            return {"fehler": "Login abgelaufen – Claude Code einmal starten"}
        return {"fehler": f"Limitabfrage fehlgeschlagen ({code or type(e).__name__})"}
    namen = {"weekly_all": "Woche (alle Modelle)", "weekly_scoped": "Woche", "session": "5 Stunden"}
    out = []
    for l in d.get("limits") or []:
        n = namen.get(l.get("kind"), l.get("kind"))
        mod = ((l.get("scope") or {}).get("model") or {}).get("display_name")
        if mod:
            n = f"{n} ({mod})"
        out.append({"name": n, "prozent": l.get("percent"), "reset": l.get("resets_at"), "aktiv": l.get("is_active")})
    fh = d.get("five_hour")
    if fh and not any(x["name"].startswith("5 Stunden") for x in out):
        out.insert(0, {"name": "5 Stunden", "prozent": fh.get("utilization"), "reset": fh.get("resets_at"), "aktiv": True})
    sd = d.get("seven_day") or {}
    return {"limits": out, "woche_reset": sd.get("resets_at")}


def auswerten(tage=None, limits=True):
    p = lade_preise()
    jetzt = datetime.now(timezone.utc)
    lim = offizielle_limits() if limits else {"fehler": "nicht abgefragt"}
    start = None
    if tage is None and lim.get("woche_reset"):
        try:  # echtes Anthropic-Wochenfenster: Reset minus 7 Tage
            start = datetime.fromisoformat(lim["woche_reset"]) - timedelta(days=7)
        except ValueError:
            pass
    if start is None:
        tage, art = tage or 7, "rollierend"
        start = jetzt - timedelta(days=tage)
    else:
        tage, art = 7, "Anthropic-Wochenfenster"
    start_ts = start.timestamp()
    recs = {}
    projekte = defaultdict(lambda: {"summe": neu_summe(), "agenten": {}, "modelle": defaultdict(neu_summe)})
    gesamt = neu_summe()
    unbekannte_modelle = set()

    for datei in glob.glob(os.path.join(PROJEKTE, "**", "*.jsonl"), recursive=True):
        try:
            if os.path.getmtime(datei) < start_ts:
                continue
        except OSError:
            continue
        rel = os.path.relpath(datei, PROJEKTE).split(os.sep)
        ordner = rel[0]
        # Subagent-Metadaten (agent-<id>.meta.json neben der .jsonl)
        meta = {}
        if "subagents" in rel:
            mp = datei[:-6] + ".meta.json"
            try:
                with open(mp) as f:
                    meta = json.load(f)
            except (OSError, ValueError):
                pass
        try:
            fh = open(datei, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for zeile in fh:
                if '"usage"' not in zeile:
                    continue
                try:
                    o = json.loads(zeile)
                except ValueError:
                    continue
                if o.get("type") != "assistant":
                    continue
                m = o.get("message") or {}
                u = m.get("usage")
                if not u:
                    continue
                ts = o.get("timestamp")
                try:
                    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except (AttributeError, ValueError):
                    continue
                if t < start:
                    continue
                key = (m.get("id"), o.get("requestId"))
                if key == (None, None):
                    key = (datei, len(recs))
                model = m.get("model") or "?"
                if model == "<synthetic>":
                    continue
                if not familie(model):
                    unbekannte_modelle.add(model)
                eur = kosten_eur(u, model, p)
                proj = projektname(o.get("cwd"), ordner)
                sid = (o.get("sessionId") or "?")[:8]
                if o.get("isSidechain") or o.get("agentId"):
                    typ = meta.get("agentType") or o.get("attributionAgent") or "subagent"
                    akey = f"{sid}/{o.get('agentId', '?')}"
                    beschr = meta.get("description", "")
                else:
                    typ, akey, beschr = "Hauptsitzung", sid, ""
                # Streaming: spätere (kumulative) Einträge derselben Nachricht ersetzen frühere
                eff = o.get("effort") or meta.get("effort") or "–"
                recs[key] = (proj, akey, typ, sid, beschr, model, ts, u, eur, eff)

    nach_effort = defaultdict(neu_summe)
    for proj, akey, typ, sid, beschr, model, ts, u, eur, eff in recs.values():
                addiere(nach_effort[eff], u, eur)
                P = projekte[proj]
                a = P["agenten"].setdefault(akey, {"typ": typ, "sitzung": sid,
                                                     "beschreibung": beschr, "modell": model,
                                                     "effort": eff,
                                                     "summe": neu_summe(), "zuletzt": ts})
                if eff not in a["effort"].split("/"):
                    a["effort"] += "/" + eff
                a["zuletzt"] = max(a["zuletzt"], ts)
                addiere(a["summe"], u, eur)
                addiere(P["summe"], u, eur)
                addiere(P["modelle"][model], u, eur)
                addiere(gesamt, u, eur)

    liste = []
    for name, P in projekte.items():
        ag = sorted(P["agenten"].values(), key=lambda a: -a["summe"]["eur"])
        for a in ag:
            a["summe"]["tokens"] = total(a["summe"])
        P["summe"]["tokens"] = total(P["summe"])
        liste.append({"projekt": name, "summe": P["summe"], "agenten": ag,
                      "modelle": {k: dict(v, tokens=total(v)) for k, v in P["modelle"].items()}})
    liste.sort(key=lambda x: -x["summe"]["eur"])
    gesamt["tokens"] = total(gesamt)
    return {"fenster_start": start.isoformat(), "fenster_ende": jetzt.isoformat(), "tage": tage,
            "fenster_art": art,
            "nach_effort": {k: dict(v, tokens=total(v)) for k, v in sorted(nach_effort.items(), key=lambda x: -x[1]["eur"])},
            "limits": lim.get("limits", []), "limit_fehler": lim.get("fehler"), "woche_reset": lim.get("woche_reset"),
            "gesamt": gesamt, "projekte": liste, "preis_stand": p.get("_stand", ""),
            "unbekannte_modelle": sorted(unbekannte_modelle)}


def fmt(n):
    for e, s in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if n >= e:
            return f"{n / e:.1f}{s}"
    return str(n)


def eur(x):
    return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def reset_text(iso):
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%a %d.%m. %H:%M")
    except (TypeError, ValueError):
        return "?"


def tabelle(d):
    for l in d["limits"]:
        print(f"Limit {l['name']}: {l['prozent']} %  (Reset {reset_text(l['reset'])})")
    if d["limit_fehler"]:
        print("Limits:", d["limit_fehler"])
    print(f"Fenster: {d['fenster_art']} ab {reset_text(d['fenster_start'])}  |  Gesamt {fmt(d['gesamt']['tokens'])} Tokens  ≈ {eur(d['gesamt']['eur'])}")
    print(f"{'Projekt':28} {'Tokens':>9} {'Output':>8} {'Agenten':>7} {'Euro':>11}")
    for p in d["projekte"]:
        s = p["summe"]
        print(f"{p['projekt'][:28]:28} {fmt(s['tokens']):>9} {fmt(s['output']):>8} {len(p['agenten']):>7} {eur(s['eur']):>11}")
    print("Nach Effort:", " | ".join(f"{k}: {fmt(v['tokens'])} · {eur(v['eur'])}" for k, v in d["nach_effort"].items()))
    if d["unbekannte_modelle"]:
        print("Ohne Preis:", ", ".join(d["unbekannte_modelle"]))
    print("Preise:", d["preis_stand"])


def html_bericht(d):
    e = html.escape
    zeilen = []
    for i, p in enumerate(d["projekte"]):
        s = p["summe"]
        zeilen.append(f"<tr class=p onclick=\"document.getElementById('d{i}').toggleAttribute('hidden')\">"
                      f"<td>▸ {e(p['projekt'])}</td><td>{fmt(s['tokens'])}</td><td>{fmt(s['output'])}</td>"
                      f"<td>{len(p['agenten'])}</td><td>{eur(s['eur'])}</td></tr>")
        sub = "".join(
            f"<tr><td>{e(a['typ'])}</td><td>{e(a['sitzung'])}</td><td>{e(a['modell'])} · {e(a['effort'])}</td>"
            f"<td>{e(a['beschreibung'])}</td><td>{fmt(a['summe']['tokens'])}</td>"
            f"<td>{fmt(a['summe']['output'])}</td><td>{eur(a['summe']['eur'])}</td></tr>"
            for a in p["agenten"])
        zeilen.append(f"<tr id=d{i} hidden><td colspan=5><table class=sub><tr><th>Agent</th><th>Sitzung</th>"
                      f"<th>Modell</th><th>Aufgabe</th><th>Tokens</th><th>Output</th><th>Euro</th></tr>{sub}</table></td></tr>")
    g = d["gesamt"]
    doc = f"""<!doctype html><meta charset=utf-8><title>Tokenzähler</title>
<style>:root{{color-scheme:light dark;--bg:#fff;--fg:#111;--mut:#666;--ln:#ddd}}
@media(prefers-color-scheme:dark){{:root{{--bg:#161616;--fg:#eee;--mut:#999;--ln:#333}}}}
body{{font:14px -apple-system,system-ui;background:var(--bg);color:var(--fg);margin:24px auto;max-width:1100px;padding:0 16px}}
table{{border-collapse:collapse;width:100%}}td,th{{padding:6px 8px;border-bottom:1px solid var(--ln);text-align:left}}
tr.p{{cursor:pointer}}td:nth-child(n+2){{font-variant-numeric:tabular-nums}}.sub{{font-size:12px;margin:4px 0 8px 16px}}
.k{{display:flex;gap:32px;margin:16px 0}}.k b{{font-size:24px;display:block}}small{{color:var(--mut)}}</style>
<h1>Tokenzähler</h1><small>{e(d['fenster_art'])} · {e(reset_text(d['fenster_start']))} bis {e(reset_text(d['fenster_ende']))}</small>
<div class=k>{''.join(f"<div><b>{e(str(l['prozent']))} %</b>{e(l['name'])}<br><small>Reset {e(reset_text(l['reset']))}</small></div>" for l in d['limits'])}{e(d['limit_fehler'] or '')}</div>
<div class=k><div><b>{fmt(g['tokens'])}</b>Tokens gesamt</div><div><b>{fmt(g['output'])}</b>Output</div>
<div><b>{eur(g['eur'])}</b>API-Gegenwert</div><div><b>{g['anfragen']}</b>Anfragen</div></div>
<p>Nach Effort: {' · '.join(f"<b>{e(k)}</b> {fmt(v['tokens'])} / {eur(v['eur'])}" for k, v in d['nach_effort'].items())}</p>
<table><tr><th>Projekt</th><th>Tokens</th><th>Output</th><th>Agenten</th><th>Euro</th></tr>{''.join(zeilen)}</table>
<p><small>Tokens = Input + Output + Cache schreiben + Cache lesen. Euro = Gegenwert zu API-Preisen, nicht Abo-Kosten.
Preise: {e(d['preis_stand'])}. Klick auf ein Projekt zeigt die Agenten.</small></p>"""
    pfad = os.environ.get("TOKENZAEHLER_BERICHT") or os.path.join(HIER, "bericht.html")
    with open(pfad, "w") as f:
        f.write(doc)
    return pfad


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--html", action="store_true")
    ap.add_argument("--tage", type=int, default=None, help="rollierendes Fenster statt Anthropic-Woche")
    ap.add_argument("--ohne-limits", action="store_true", help="Schlüsselbund/Limitabfrage überspringen")
    a = ap.parse_args()
    d = auswerten(a.tage, limits=not a.ohne_limits)
    if a.json:
        json.dump(d, sys.stdout, ensure_ascii=False)
    elif a.html:
        print(html_bericht(d))
    else:
        tabelle(d)
