#!/usr/bin/env python3
"""bruecken_schleusen.py – erzeugt Bruecken_Schleusen_NL.csv aus den offenen Daten von Rijkswaterstaat (Vaarweginformatie).

Aufruf:  python3 bruecken_schleusen.py [Ausgabedatei]
Benötigte freigegebene Domain: www.vaarweginformatie.nl
Einmal pro Saison neu ausführen (vor Saisonbeginn im Frühjahr und vor der Winterzeit) und die neue Datei
auf GitHub hochladen. Die Tabelle enthält nur dauerhafte Daten (Lage, Durchfahrtshöhe, beweglich ja/nein).
Bedienzeiten, UKW-Kanäle und aktuelle Sperrungen holt der Planer bei jeder Planung live (siehe Spalte detail_url).
"""
import csv, datetime, re, sys, time, urllib.request, xml.etree.ElementTree as ET

WFS = "https://www.vaarweginformatie.nl/wfswms/services?SERVICE=WFS&VERSION=1.1.0&REQUEST=GetFeature&TYPENAME=app:{t}&BBOX={b}"
API = "https://www.vaarweginformatie.nl/frp/api/geo/{art}/{id}"
NS = {"app": "http://www.deegree.org/app", "gml": "http://www.opengis.net/gml"}
UA = {"User-Agent": "Toernplaner-Segelplanung/1.0 (private Toernplanung)"}
# Niederlande in Kacheln abfragen (der Dienst liefert höchstens 3000 Objekte je Anfrage)
LAT, LON = (50.70, 53.70), (3.30, 7.30)

def get(url):
    for _ in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
                return r.read()
        except Exception as e:
            err = e; time.sleep(3)
    raise err

def features(typ, n=4):
    out = {}
    for i in range(n):
        for j in range(n):
            la0 = LAT[0] + (LAT[1] - LAT[0]) * i / n; la1 = LAT[0] + (LAT[1] - LAT[0]) * (i + 1) / n
            lo0 = LON[0] + (LON[1] - LON[0]) * j / n; lo1 = LON[0] + (LON[1] - LON[0]) * (j + 1) / n
            root = ET.fromstring(get(WFS.format(t=typ, b=f"{lo0},{la0},{lo1},{la1},EPSG:4326")))
            fs = root.findall(f".//app:{typ}", NS)
            if len(fs) >= 3000:
                sys.exit(f"{typ}: Kachel mit 3000 Objekten – Kachelzahl erhöhen")
            for f in fs:
                fid = f.get("{http://www.opengis.net/gml}id")
                pos = f.find(".//gml:pos", NS)
                if pos is None:
                    pos = f.find(".//gml:posList", NS)
                if pos is None:
                    continue
                c = pos.text.split()
                rec = {"lon": float(c[0]), "lat": float(c[1])}
                for ch in f:
                    tag = ch.tag.split("}")[1]
                    if ch.text and ch.text.strip() and len(ch) == 0:
                        rec[tag] = ch.text.strip()
                out[fid] = rec
            time.sleep(0.3)
    return out

def dist_m(a, b):
    import math
    return math.hypot((a["lon"] - b["lon"]) * 111320 * math.cos(math.radians(a["lat"])), (a["lat"] - b["lat"]) * 110540)

def main():
    ziel = sys.argv[1] if len(sys.argv) > 1 else "Bruecken_Schleusen_NL.csv"
    bridges, openings, locks = features("Bridge"), features("Opening"), features("Lock")
    print(f"Brücken {len(bridges)}, Durchfahrtsöffnungen {len(openings)}, Schleusen {len(locks)}")
    # Öffnungen der nächstgelegenen Brücke (max. 80 m) zuordnen
    grid = {}
    for bid, b in bridges.items():
        grid.setdefault((round(b["lat"], 2), round(b["lon"], 2)), []).append(bid)
    per_bridge = {}
    for o in openings.values():
        best, bd = None, 80
        for dla in (-0.01, 0, 0.01):
            for dlo in (-0.01, 0, 0.01):
                for bid in grid.get((round(o["lat"] + dla, 2), round(o["lon"] + dlo, 2)), []):
                    d = dist_m(o, bridges[bid])
                    if d < bd:
                        best, bd = bid, d
        if best:
            per_bridge.setdefault(best, []).append(o)
    stand = datetime.date.today().isoformat()
    rows = []
    for bid, b in bridges.items():
        ops = per_bridge.get(bid, [])
        hoehen = [float(o["HeightClosed"]) for o in ops if "HeightClosed" in o]
        num = re.sub(r"\D", "", bid)
        rows.append(["Brücke", b.get("Name", ""), b.get("City", ""), round(b["lat"], 5), round(b["lon"], 5),
                     "ja" if b.get("CanOpen") == "true" else "nein",
                     f"{max(hoehen):.2f}" if hoehen else "", b.get("Referencelevel", ""), b.get("PhoneNumber", ""),
                     API.format(art="bridge", id=num), API.format(art="operating_schedule", id=num), stand])
    for lid, l in locks.items():
        num = re.sub(r"\D", "", lid)
        rows.append(["Schleuse", l.get("Name", ""), l.get("City", ""), round(l["lat"], 5), round(l["lon"], 5),
                     "", "", l.get("ReferenceLevelBeBu", ""), l.get("PhoneNumber", ""),
                     API.format(art="lock", id=num), API.format(art="operating_schedule", id=num), stand])
    rows.sort(key=lambda r: (r[0], r[2], r[1]))
    with open(ziel, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["art", "name", "ort", "lat", "lon", "beweglich", "durchfahrtshoehe_geschlossen_m", "bezugsniveau",
                    "telefon", "detail_url", "bedienzeiten_url", "stand"])
        w.writerows(rows)
    print(f"{ziel}: {len(rows)} Zeilen, Stand {stand}")

if __name__ == "__main__":
    main()
