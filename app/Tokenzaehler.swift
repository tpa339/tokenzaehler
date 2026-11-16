import SwiftUI
import AppKit
import ServiceManagement

struct Summe: Decodable { let tokens: Int; let output: Int; let eur: Double; let anfragen: Int? }
struct Agent: Decodable { let typ: String; let beschreibung: String; let modell: String; let effort: String; let summe: Summe }
struct Projekt: Decodable, Identifiable { let projekt: String; let summe: Summe; let agenten: [Agent]; var id: String { projekt } }
struct Limit: Decodable { let name: String; let prozent: Double?; let reset: String?; let aktiv: Bool? }
struct Daten: Decodable {
    let tage: Int; let gesamt: Summe; let projekte: [Projekt]
    let fenster_art: String; let limits: [Limit]; let limit_fehler: String?
}

func resetText(_ iso: String?) -> String {
    guard let iso else { return "–" }
    let p = ISO8601DateFormatter(); p.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    let d = p.date(from: iso) ?? { p.formatOptions = [.withInternetDateTime]; return p.date(from: iso) }()
    guard let d else { return "–" }
    let f = DateFormatter(); f.locale = Locale(identifier: "de_DE"); f.dateFormat = "EE dd.MM. HH:mm"
    return f.string(from: d)
}

enum Autostart {
    static var an: Bool { SMAppService.mainApp.status == .enabled }
    static func umschalten() {
        do { if an { try SMAppService.mainApp.unregister() } else { try SMAppService.mainApp.register() } }
        catch { NSLog("Autostart: \(error)") }
    }
}

let skript = (Bundle.main.object(forInfoDictionaryKey: "TZSkript") as? String)
    ?? NSString(string: "~/Claude/tokenzaehler/tokenzaehler.py").expandingTildeInPath

func fmt(_ n: Int) -> String {
    let d = Double(n)
    if d >= 1e9 { return String(format: "%.1f Mrd", d / 1e9).replacingOccurrences(of: ".", with: ",") }
    if d >= 1e6 { return String(format: "%.1f Mio", d / 1e6).replacingOccurrences(of: ".", with: ",") }
    if d >= 1e3 { return String(format: "%.0fk", d / 1e3) }
    return "\(n)"
}
func eur(_ x: Double) -> String {
    let f = NumberFormatter(); f.locale = Locale(identifier: "de_DE"); f.numberStyle = .currency; f.currencyCode = "EUR"
    return f.string(from: NSNumber(value: x)) ?? "\(x) €"
}
func kurzModell(_ m: String) -> String { m.replacingOccurrences(of: "claude-", with: "") }

func lauf(_ args: [String]) -> Data? {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    p.arguments = ["python3", skript] + args
    var env = ProcessInfo.processInfo.environment
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    p.environment = env
    let pipe = Pipe(); p.standardOutput = pipe
    do { try p.run() } catch { return nil }
    let d = pipe.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return p.terminationStatus == 0 ? d : nil
}

@MainActor final class Modell: ObservableObject {
    @Published var daten: Daten?
    @Published var fehler = false
    @Published var laeuft = false
    @Published var stand: Date?
    @Published var autostart = Autostart.an
    private var timer: Timer?
    init() {
        // Autostart beim ersten Start einschalten; danach gilt die Wahl im Panel.
        if !UserDefaults.standard.bool(forKey: "autostartGesetzt") {
            if !Autostart.an { Autostart.umschalten() }
            UserDefaults.standard.set(true, forKey: "autostartGesetzt")
            autostart = Autostart.an
        }
        aktualisieren()
        timer = Timer.scheduledTimer(withTimeInterval: 300, repeats: true) { _ in
            Task { @MainActor in self.aktualisieren() }
        }
    }
    func aktualisieren() {
        guard !laeuft else { return }
        laeuft = true
        Task.detached {
            let d = lauf(["--json"]).flatMap { try? JSONDecoder().decode(Daten.self, from: $0) }
            await MainActor.run {
                if let d { self.daten = d; self.stand = Date() }
                self.fehler = (d == nil); self.laeuft = false
            }
        }
    }
    /// Beim Öffnen des Panels nur neu zählen, wenn der Stand älter als eine Minute ist.
    func aktualisierenWennAlt() {
        if let s = stand, Date().timeIntervalSince(s) < 60 { return }
        aktualisieren()
    }
    func bericht() {
        Task.detached {
            guard let d = lauf(["--html"]), let pfad = String(data: d, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) else { return }
            NSWorkspace.shared.open(URL(fileURLWithPath: pfad))
        }
    }
}

// MARK: - Bausteine

/// Farbe trägt Bedeutung: grün = Luft, orange = knapp, rot = fast erschöpft.
func limitFarbe(_ p: Double) -> Color { p >= 85 ? .red : (p >= 60 ? .orange : .green) }

struct Balken: View {
    let anteil: Double   // 0…1
    let farbe: Color
    var hoehe: CGFloat = 6
    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.primary.opacity(0.08))
                Capsule().fill(farbe)
                    .frame(width: max(anteil > 0 ? hoehe : 0, g.size.width * min(max(anteil, 0), 1)))
            }
        }
        .frame(height: hoehe)
    }
}

struct LimitZeile: View {
    let l: Limit
    var body: some View {
        let p = l.prozent ?? 0
        let inaktiv = l.aktiv == false
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline) {
                Text(l.name).font(.system(size: 12, weight: .medium))
                Spacer()
                Text(l.prozent.map { "\(Int($0.rounded())) %" } ?? "–")
                    .font(.system(size: 20, weight: .semibold, design: .rounded)).monospacedDigit()
                    .foregroundStyle(inaktiv ? .secondary : .primary)
            }
            Balken(anteil: p / 100, farbe: inaktiv ? .secondary : limitFarbe(p), hoehe: 8)
            Text("Reset \(resetText(l.reset))").font(.system(size: 10.5)).foregroundStyle(.secondary)
        }
    }
}

struct Kennzahl: View {
    let wert: String; let titel: String
    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(wert).font(.system(size: 15, weight: .semibold, design: .rounded)).monospacedDigit()
            Text(titel).font(.system(size: 10.5)).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct ProjektZeile: View {
    let p: Projekt
    let gesamt: Double
    let groesstes: Double
    @Binding var offen: Set<String>
    var body: some View {
        let istOffen = offen.contains(p.id)
        VStack(alignment: .leading, spacing: 4) {
            Button {
                withAnimation(.easeOut(duration: 0.15)) {
                    if istOffen { offen.remove(p.id) } else { offen.insert(p.id) }
                }
            } label: {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        Image(systemName: "chevron.right")
                            .font(.system(size: 9, weight: .semibold)).foregroundStyle(.tertiary)
                            .rotationEffect(.degrees(istOffen ? 90 : 0))
                        Text(p.projekt).font(.system(size: 12.5, weight: .medium)).lineLimit(1)
                        Spacer(minLength: 8)
                        Text(eur(p.summe.eur)).font(.system(size: 12.5, weight: .semibold)).monospacedDigit()
                    }
                    HStack(spacing: 8) {
                        // Länge relativ zum größten Projekt; die Zahl daneben ist der Anteil am Gesamtwert.
                        Balken(anteil: groesstes > 0 ? p.summe.eur / groesstes : 0, farbe: .accentColor)
                        Text("\(gesamt > 0 ? Int((p.summe.eur / gesamt * 100).rounded()) : 0) % · \(fmt(p.summe.tokens))")
                            .font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit()
                            .frame(width: 92, alignment: .trailing)
                    }
                    .padding(.leading, 15)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if istOffen {
                let ag = p.agenten.sorted { $0.summe.eur > $1.summe.eur }
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(Array(ag.prefix(5).enumerated()), id: \.offset) { _, a in
                        HStack(spacing: 6) {
                            Text(a.beschreibung.isEmpty ? a.typ : "\(a.typ): \(a.beschreibung)")
                                .lineLimit(1).truncationMode(.tail)
                            Spacer(minLength: 6)
                            Text(kurzModell(a.modell)).foregroundStyle(.tertiary)
                            Text(eur(a.summe.eur)).monospacedDigit().frame(width: 62, alignment: .trailing)
                        }
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                    if ag.count > 5 {
                        Text("+ \(ag.count - 5) weitere Agenten im Bericht")
                            .font(.system(size: 10.5)).foregroundStyle(.tertiary)
                    }
                }
                .padding(.leading, 15).padding(.top, 2)
            }
        }
    }
}

// MARK: - Panel

struct Dashboard: View {
    @ObservedObject var m: Modell
    @State private var alleProjekte = false
    @State private var offen: Set<String> = []

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            kopf
            if let d = m.daten { inhalt(d) }
            else {
                Text(m.fehler ? "Fehler beim Auswerten der Protokolle" : "Wird gezählt …")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 60)
            }
            Divider()
            fuss
        }
        .padding(16)
        .frame(width: 360)
        .onAppear { m.aktualisierenWennAlt() }
    }

    private var untertitel: String {
        guard let d = m.daten else { return "" }
        let fenster = d.fenster_art == "rollierend" ? "Letzte \(d.tage) Tage" : "Aktuelle Limitwoche"
        let s = m.stand.map { " · Stand " + $0.formatted(date: .omitted, time: .shortened) } ?? ""
        return fenster + s
    }

    private var kopf: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 1) {
                Text("Tokenzähler").font(.system(size: 14, weight: .semibold))
                Text(untertitel).font(.system(size: 10.5)).foregroundStyle(.secondary)
            }
            Spacer()
            if m.laeuft { ProgressView().controlSize(.small) }
            Button { m.aktualisieren() } label: { Image(systemName: "arrow.clockwise") }
                .buttonStyle(.borderless).help("Aktualisieren").disabled(m.laeuft)
        }
    }

    @ViewBuilder private func inhalt(_ d: Daten) -> some View {
        // 1. Limits: die Frage, die das Panel zuerst beantwortet.
        if !d.limits.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                ForEach(Array(d.limits.enumerated()), id: \.offset) { _, l in LimitZeile(l: l) }
            }
        } else {
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.circle")
                Text(d.limit_fehler ?? "Keine Limitdaten")
            }
            .font(.system(size: 11)).foregroundStyle(.secondary)
        }

        Divider()

        // 2. Verbrauch im Fenster als Zahlen, ohne Kacheln.
        HStack(spacing: 8) {
            Kennzahl(wert: eur(d.gesamt.eur), titel: "API-Gegenwert")
            Kennzahl(wert: fmt(d.gesamt.tokens), titel: "Tokens")
            Kennzahl(wert: d.gesamt.anfragen.map { $0.formatted(.number.locale(Locale(identifier: "de_DE"))) } ?? "–", titel: "Anfragen")
        }

        // 3. Top 5 Projekte, der Rest zum Aufklappen.
        let projekte = d.projekte.sorted { $0.summe.eur > $1.summe.eur }
        let groesstes = projekte.first?.summe.eur ?? 0
        VStack(alignment: .leading, spacing: 10) {
            Text("Top-Projekte").font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
            ForEach(projekte.prefix(5)) { p in
                ProjektZeile(p: p, gesamt: d.gesamt.eur, groesstes: groesstes, offen: $offen)
            }
            if projekte.count > 5 {
                if alleProjekte {
                    ForEach(projekte.dropFirst(5).prefix(20)) { p in
                        ProjektZeile(p: p, gesamt: d.gesamt.eur, groesstes: groesstes, offen: $offen)
                    }
                }
                Button {
                    withAnimation(.easeOut(duration: 0.15)) { alleProjekte.toggle() }
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: alleProjekte ? "chevron.up" : "chevron.down").font(.system(size: 9, weight: .semibold))
                        Text(alleProjekte ? "Weniger anzeigen" : "\(projekte.count - 5) weitere Projekte anzeigen")
                    }
                    .font(.system(size: 11.5)).foregroundStyle(Color.accentColor)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var fuss: some View {
        HStack {
            Button("Bericht öffnen") { m.bericht() }
            Spacer()
            Toggle("Autostart", isOn: Binding(get: { m.autostart },
                                              set: { _ in Autostart.umschalten(); m.autostart = Autostart.an }))
                .toggleStyle(.checkbox)
            Button("Beenden") { NSApp.terminate(nil) }
        }
        .font(.system(size: 11.5))
        .controlSize(.small)
    }
}

@main struct TokenzaehlerApp: App {
    @StateObject var m = Modell()
    var body: some Scene {
        MenuBarExtra {
            Dashboard(m: m)
        } label: {
            Text(m.daten.map { d in
                let w = d.limits.first.map { "\(Int(($0.prozent ?? 0).rounded())) % · " } ?? ""
                return "◆ \(w)\(eur(d.gesamt.eur))"
            } ?? "◆ …")
        }
        .menuBarExtraStyle(.window)
    }
}
