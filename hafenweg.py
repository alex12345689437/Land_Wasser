#!/usr/bin/env python3
"""hafenweg.py – berechnet den Weg vom Hafen bis ins offene Wasser (IJsselmeer, Markermeer, IJmeer).

Aufruf als Skript:   python3 hafenweg.py <lat> <lon> [Name]
Aufruf aus Python:   from hafenweg import hafenweg; hafenweg(52.8857, 5.3599)

Ergebnis: Wegpunkte vom Hafen bis zum Ansteuerungspunkt im offenen Wasser (mind. 250 m Abstand zu Ufer
und Hindernissen), Länge in sm und ob eine Schleuse passiert wird. Der Weg führt nur über Wasserflächen
(Hafenbecken, Kanäle, Schleusen, See) und umgeht Molen, Stege, Wellenbrecher, Buhnen und Kaimauern.
Daten: Hafen_Wasser_IJM.geojson (OpenStreetMap, Stand 22.10.2026) – wird von GitHub geladen, wenn sie nicht lokal liegt.
Grobplanung – nicht zur Navigation. Hafenein- und -ausfahrt nach Sicht und Betonnung.
"""
import heapq, json, math, os, sys, urllib.request
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

DATEN_URL = "https://raw.githubusercontent.com/alex12345689437/Land_Wasser/main/Hafen_Wasser_IJM.geojson"
DATEN = "Hafen_Wasser_IJM.geojson"
OFFEN = {"IJsselmeer", "Markermeer", "IJmeer"}
RES = 8.0          # Meter je Rasterzelle
HALB = 2200.0      # halbe Fensterbreite in Metern
FREI = 250.0       # Mindestabstand des Ansteuerungspunkts zu Ufer/Hindernissen in Metern
_daten = None

def lade():
    global _daten
    if _daten is None:
        if not os.path.exists(DATEN):
            req = urllib.request.Request(DATEN_URL, headers={"User-Agent": "Toernplaner/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r, open(DATEN, "wb") as f:
                f.write(r.read())
        _daten = json.load(open(DATEN, encoding="utf-8"))["features"]
    return _daten

def _rings(g):
    if g["type"] == "Polygon":
        return [g["coordinates"]]
    if g["type"] == "MultiPolygon":
        return g["coordinates"]
    return []

def hafenweg(lat, lon, name=""):
    # Fenster schrittweise vergrößern, falls das offene Wasser weiter entfernt ist (z. B. Häfen an Kanälen)
    for halb, res in ((2200.0, 8.0), (4500.0, 12.0), (8000.0, 18.0)):
        r = _hafenweg(lat, lon, name, halb, res)
        if r["ok"] or r.get("verbunden") is False or "nicht mit offenem Wasser verbunden" in r["grund"]:
            return r
    return r

def _hafenweg(lat, lon, name, HALB, RES):
    feats = lade()
    kx = 111320 * math.cos(math.radians(lat)) / RES
    ky = 110540 / RES
    n = int(2 * HALB / RES)
    def P(x, y):  # lon, lat -> Pixel
        return ((x - lon) * kx + n / 2, (lat - y) * ky + n / 2)
    def G(px, py):  # Pixel -> lat, lon
        return (lat - (py - n / 2) / ky, lon + (px - n / 2) / kx)
    dlon, dlat = (n / 2 + 5) / kx, (n / 2 + 5) / ky
    def nah(coords):
        return any(abs(c[0] - lon) < dlon and abs(c[1] - lat) < dlat for c in coords)

    wasser = Image.new("L", (n, n), 0); dw = ImageDraw.Draw(wasser)
    offen = Image.new("L", (n, n), 0); do = ImageDraw.Draw(offen)
    schleuse = Image.new("L", (n, n), 0); ds = ImageDraw.Draw(schleuse)
    hind = []; tore = []
    for f in feats:
        p, g = f["properties"], f["geometry"]
        if p["k"] == "wasser":
            for poly in _rings(g):
                if not poly or len(poly[0]) < 3 or not (nah(poly[0]) or _umschliesst(poly[0], lon, lat)):
                    continue
                dw.polygon([P(*c) for c in poly[0]], fill=1)
                for hole in poly[1:]:
                    if len(hole) >= 3:
                        dw.polygon([P(*c) for c in hole], fill=0)
                if p["n"] in OFFEN:
                    do.polygon([P(*c) for c in poly[0]], fill=1)
                    for hole in poly[1:]:
                        if len(hole) >= 3:
                            do.polygon([P(*c) for c in hole], fill=0)
                if p["w"] == "lock":
                    ds.polygon([P(*c) for c in poly[0]], fill=1)
        elif p["k"] == "schleusentor":
            # Schleusentore verbinden die Wasserflächen auf beiden Seiten (Schleusenkammern fehlen oft als Fläche)
            cs = [g["coordinates"]] if g["type"] == "Point" else g["coordinates"]
            if cs and nah(cs):
                tore.append([P(*c) for c in cs])
        elif p["k"] == "hindernis":
            cs = g["coordinates"] if g["type"] == "LineString" else g["coordinates"][0] if g["type"] == "Polygon" else []
            if cs and nah(cs):
                hind.append((g["type"], cs))
    for typ, cs in hind:
        pts = [P(*c) for c in cs]
        if typ == "Polygon" and len(pts) >= 3:
            dw.polygon(pts, fill=0)
        dw.line(pts, fill=0, width=2)
    r_tor = max(2, int(round(20 / RES)))
    for pts in tore:
        for (x, y) in pts:
            dw.ellipse([x - r_tor, y - r_tor, x + r_tor, y + r_tor], fill=1)
            ds.ellipse([x - r_tor, y - r_tor, x + r_tor, y + r_tor], fill=1)
        if len(pts) > 1:
            dw.line(pts, fill=1, width=2 * r_tor); ds.line(pts, fill=1, width=2 * r_tor)
    W = np.array(wasser, dtype=bool)
    O = np.array(offen, dtype=bool) & W
    S = np.array(schleuse, dtype=bool)
    frei = ndimage.distance_transform_edt(W) * RES
    ziel = O & (frei >= FREI)
    if not ziel.any():
        return {"ok": False, "grund": "kein offenes Wasser im Umkreis von %.1f km gefunden" % (HALB / 1000)}
    lab, _ = ndimage.label(W, structure=np.ones((3, 3)))
    gute = set(np.unique(lab[ziel])) - {0}
    erreichbar = np.isin(lab, list(gute))
    sx, sy = P(lon, lat)
    ys, xs = np.nonzero(erreichbar)
    if len(xs) == 0:
        return {"ok": False, "grund": "Hafen nicht mit offenem Wasser verbunden (Daten prüfen)"}
    i = int(np.argmin((xs - sx) ** 2 + (ys - sy) ** 2))
    start = (int(ys[i]), int(xs[i]))
    abstand_start = math.hypot(xs[i] - sx, ys[i] - sy) * RES
    if abstand_start > 150:
        return {"ok": False, "verbunden": False, "grund": "Hafen liegt nicht an einer Wasserfläche, die in den Daten mit IJsselmeer/Markermeer/IJmeer verbunden ist (nächste verbundene Stelle %d m entfernt). Hafen liegt evtl. außerhalb des Reviers oder die Zufahrt fehlt in den Daten – Zufahrt auf der Seekarte prüfen." % abstand_start}
    # Dijkstra: Kosten = Schrittlänge, verteuert nahe am Ufer (Weg bleibt in der Fahrwassermitte)
    strafe = 1 + 4 * np.exp(-frei / 25.0)
    dist = {start: 0.0}; vor = {}; heap = [(0.0, start)]; end = None
    nb = [(-1, 0, 1), (1, 0, 1), (0, -1, 1), (0, 1, 1), (-1, -1, 1.414), (-1, 1, 1.414), (1, -1, 1.414), (1, 1, 1.414)]
    while heap:
        d, (y, x) = heapq.heappop(heap)
        if d > dist.get((y, x), 1e18):
            continue
        if ziel[y, x]:
            end = (y, x); break
        for dy, dx, l in nb:
            yy, xx = y + dy, x + dx
            if 0 <= yy < n and 0 <= xx < n and erreichbar[yy, xx]:
                nd = d + l * strafe[yy, xx]
                if nd < dist.get((yy, xx), 1e18):
                    dist[(yy, xx)] = nd; vor[(yy, xx)] = (y, x); heapq.heappush(heap, (nd, (yy, xx)))
    if end is None:
        return {"ok": False, "grund": "kein Weg ins offene Wasser gefunden"}
    pfad = [end]
    while pfad[-1] in vor:
        pfad.append(vor[pfad[-1]])
    pfad.reverse()
    def sicht(a, b):
        k = int(max(abs(a[0] - b[0]), abs(a[1] - b[1]))) + 1
        for t in range(k + 1):
            y = round(a[0] + (b[0] - a[0]) * t / k); x = round(a[1] + (b[1] - a[1]) * t / k)
            if frei[y, x] < 6:  # mindestens 6 m Abstand zu Ufer/Hindernis entlang der Linie
                return False
        return True
    punkte = [pfad[0]]; j = 0
    while j < len(pfad) - 1:
        k = len(pfad) - 1
        while k > j + 1 and not sicht(pfad[j], pfad[k]):
            k -= 1
        punkte.append(pfad[k]); j = k
    laenge = sum(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(pfad, pfad[1:])) * RES / 1852
    wp = [[round(v, 5) for v in G(x + 0.5, y + 0.5)] for y, x in punkte]
    return {"ok": True, "hafen": name, "wegpunkte": wp, "laenge_sm": round(laenge + abstand_start / 1852, 2),
            "schleuse": bool(any(S[y, x] for y, x in pfad)), "start_abstand_m": round(abstand_start),
            "hinweis": "Hafenausfahrt nach Sicht und Betonnung – Grobplanung, nicht zur Navigation"}

def _umschliesst(ring, x, y):
    ins = False; j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]; xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi:
            ins = not ins
        j = i
    return ins

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    print(json.dumps(hafenweg(float(sys.argv[1]), float(sys.argv[2]), " ".join(sys.argv[3:])), ensure_ascii=False, indent=1))
