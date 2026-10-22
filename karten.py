#!/usr/bin/env python3
"""karten.py – erzeugt die Karten für die Onepager-Vorlagen und bettet sie als Bilder ein.

Aufruf:  python3 karten.py Onepager_Skipper.html [Onepager_Mitsegler.html ...]

Liest in jeder HTML-Datei das Datenobjekt zwischen /*TOERN_START*/ und /*TOERN_ENDE*/ (gültiges JSON),
lädt Kartenkacheln von OpenStreetMap (Grundkarte) und OpenSeaMap (Seezeichen), zeichnet Route,
Häfen, Wechselpunkte und kritische Punkte ein und schreibt die fertigen Bilder als
TOERN_KARTEN-Block in dieselbe Datei. Danach funktioniert die HTML-Datei ohne Internet und
lässt sich als PDF drucken.
Benötigte freigegebene Domains: tile.openstreetmap.org, tiles.openseamap.org
Quelle der Karten: © OpenStreetMap-Mitwirkende (ODbL), © OpenSeaMap (CC BY-SA)
"""
import base64, io, json, math, re, sys, time, urllib.request
from PIL import Image, ImageDraw, ImageFont

UA = {"User-Agent": "Toernplaner-Segelplanung/1.0 (private Toernplanung, wenige Kacheln je Plan)"}
OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
SEA = "https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png"
COL = {"sail": (31, 111, 178), "motor": (224, 123, 0), "direkt": (18, 48, 79),
       "crit": (198, 40, 40), "warn": (242, 183, 5), "check": (123, 79, 179)}
T = 256
_cache = {}

def font(size, bold=True):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for d in ("/usr/share/fonts/truetype/dejavu/", ""):
        try:
            return ImageFont.truetype(d + name, size)
        except OSError:
            pass
    return ImageFont.load_default()

def tile(url):
    if url in _cache:
        return _cache[url]
    img = None
    for _ in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                img = Image.open(io.BytesIO(r.read())).convert("RGBA")
            break
        except Exception:
            time.sleep(1)
    _cache[url] = img
    time.sleep(0.05)
    return img

def px(lat, lon, z):
    s = T * 2 ** z
    r = math.radians(lat)
    return (lon + 180) / 360 * s, (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * s

def fit_zoom(b, w, h):
    for z in range(16, 3, -1):
        x1, y1 = px(b[2], b[1], z); x2, y2 = px(b[0], b[3], z)
        if x2 - x1 <= w * 0.86 and y2 - y1 <= h * 0.86:
            return z
    return 4

def render(T_, w, h, center=None, zoom=None, bbox=None, direkt=True, labels=True, kritisch=True, wind=False, scale=2):
    W, H = w * scale, h * scale
    if center:
        z = zoom
        cx, cy = px(center[0], center[1], z)
    else:
        z = fit_zoom(bbox, W, H)
        x1, y1 = px(bbox[2], bbox[1], z); x2, y2 = px(bbox[0], bbox[3], z)
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    ox, oy = cx - W / 2, cy - H / 2
    img = Image.new("RGBA", (W, H), (170, 211, 223, 255))
    missing = 0
    for layer in (OSM, SEA):
        for tx in range(int(ox // T), int((ox + W) // T) + 1):
            for ty in range(int(oy // T), int((oy + H) // T) + 1):
                if ty < 0 or ty >= 2 ** z:
                    continue
                t = tile(layer.format(z=z, x=tx % 2 ** z, y=ty))
                if t is None:
                    missing += layer == OSM
                    continue
                img.alpha_composite(t, (int(tx * T - ox), int(ty * T - oy)))
    d = ImageDraw.Draw(img)
    P = lambda p: (px(p[0], p[1], z)[0] - ox, px(p[0], p[1], z)[1] - oy)
    for e in T_.get("etappen", []):
        if direkt and len(e.get("direkt", [])) > 1:
            a, b = P(e["direkt"][0]), P(e["direkt"][-1])
            n = max(1, int(math.dist(a, b) / 12))
            for i in range(0, n, 2):
                d.line([(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n),
                        (a[0] + (b[0] - a[0]) * (i + 1) / n, a[1] + (b[1] - a[1]) * (i + 1) / n)], fill=COL["direkt"], width=3)
        k = e.get("kurs", [])
        for i in range(len(k) - 1):
            d.line([P(k[i]), P(k[i + 1])], fill=COL.get(k[i][2] if len(k[i]) > 2 else "sail", COL["sail"]), width=7, joint="curve")
    fb, fs = font(22), font(18)
    def dot(p, r, fill, txt="", lab=""):
        x, y = P(p)
        if not (-r < x < W + r and -r < y < H + r):
            return
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill, outline="white", width=3)
        if txt:
            d.text((x, y), txt, fill="white", font=fs, anchor="mm")
        if lab:
            d.text((x + r + 6, y), lab, fill=COL["direkt"], font=fb, anchor="lm", stroke_width=4, stroke_fill="white")
    for m in T_.get("wechsel", []):
        dot((m["lat"], m["lon"]), 9, COL["motor"] if m.get("zu") == "motor" else COL["sail"], "", m.get("text", "") if labels else "")
    if kritisch:
        for i, kp in enumerate(T_.get("kritisch", [])):
            dot((kp["lat"], kp["lon"]), 16, COL.get(kp.get("typ"), COL["crit"]), str(i + 1))
    if wind:
        # Windpfeile: zeigen in die Richtung, in die der Wind weht; Beschriftung = Herkunft und Stärke
        RICHT = ["N","NNO","NO","ONO","O","OSO","SO","SSO","S","SSW","SW","WSW","W","WNW","NW","NNW"]
        for wd in T_.get("wind", []):
            x, y = P((wd["lat"], wd["lon"]))
            if not (0 < x < W and 0 < y < H):
                continue
            to = math.radians((float(wd["richtung"]) + 180) % 360)
            L = 56 + min(float(wd.get("kn", 10)), 30) * 2.2
            dx, dy = math.sin(to), -math.cos(to)
            x0, y0, x1, y1 = x - dx * L / 2, y - dy * L / 2, x + dx * L / 2, y + dy * L / 2
            wc = (20, 110, 110)
            d.line([(x0, y0), (x1, y1)], fill="white", width=11)
            d.line([(x0, y0), (x1 - dx * 10, y1 - dy * 10)], fill=wc, width=6)
            px_, py_ = -dy, dx
            d.polygon([(x1, y1), (x1 - dx * 18 + px_ * 10, y1 - dy * 18 + py_ * 10), (x1 - dx * 18 - px_ * 10, y1 - dy * 18 - py_ * 10)], fill=wc, outline="white")
            txt = RICHT[int((float(wd["richtung"]) % 360) / 22.5 + 0.5) % 16] + " " + str(round(float(wd.get("kn", 0)))) + " kn"
            if wd.get("zeit"):
                txt += " · " + wd["zeit"]
            d.text((x0 - dx * 6, y0 - dy * 6 + 14), txt, fill=wc, font=font(17), anchor="mm", stroke_width=4, stroke_fill="white")
    for hf in T_.get("haefen", []):
        dot((hf["lat"], hf["lon"]), 11, (138, 150, 163) if hf.get("rolle") == "ausweich" else COL["direkt"], "", hf.get("name", ""))
    att = "© OpenStreetMap-Mitwirkende · © OpenSeaMap"
    tw = d.textlength(att, font=font(16, False))
    d.rectangle([W - tw - 14, H - 26, W, H], fill=(255, 255, 255, 210))
    d.text((W - 7, H - 13), att, fill=(40, 40, 40), font=font(16, False), anchor="rm")
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=82, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), missing

def bbox_all(T_):
    pts = [p for e in T_.get("etappen", []) for p in e.get("kurs", []) + e.get("direkt", [])]
    pts += [(h["lat"], h["lon"]) for h in T_.get("haefen", [])]
    return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]

def process(path):
    html = open(path, encoding="utf-8").read()
    m = re.search(r"/\*TOERN_START\*/(.*?)/\*TOERN_ENDE\*/", html, re.S)
    if not m:
        sys.exit(f"{path}: Datenblock /*TOERN_START*/ … /*TOERN_ENDE*/ nicht gefunden")
    data = json.loads(re.sub(r"^\s*var\s+TOERN\s*=\s*|;\s*$", "", m.group(1).strip()))
    art = data.get("_vorlage", "skipper")
    karten, fehlend = {}, 0
    if art == "mitsegler":
        karten["uebersicht"], f = render(data, 700, 272, bbox=bbox_all(data), direkt=False, kritisch=False, wind=True); fehlend += f
    else:
        karten["uebersicht"], f = render(data, 710, 295, bbox=bbox_all(data), wind=True); fehlend += f
        karten["details"] = []
        for kp in data.get("kritisch", []):
            img, f = render(data, 345, 234, center=(kp["lat"], kp["lon"]), zoom=int(kp.get("zoom", 15)), direkt=False, labels=False)
            karten["details"].append(img); fehlend += f
    block = "/*KARTEN_START*/var TOERN_KARTEN = " + json.dumps(karten) + ";/*KARTEN_ENDE*/"
    if "/*KARTEN_START*/" in html:
        html = re.sub(r"/\*KARTEN_START\*/.*?/\*KARTEN_ENDE\*/", lambda _: block, html, flags=re.S)
    else:
        html = html.replace("/*TOERN_ENDE*/", "/*TOERN_ENDE*/\n" + block, 1)
    open(path, "w", encoding="utf-8").write(html)
    n = 1 + len(karten.get("details", []))
    print(f"{path}: {n} Karte(n) eingebettet" + (f", {fehlend} Kartenkacheln fehlten" if fehlend else ""))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for p in sys.argv[1:]:
        process(p)
