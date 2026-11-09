#!/usr/bin/env python3
"""
Télécharge le guide XMLTV de la TNT (xmltvfr.fr), garde les chaînes 1 à 26
et écrit un petit fichier JSON par jour dans data/, lu par l'appli au démarrage.

Usage :
  python scripts/update.py              # télécharge depuis xmltvfr.fr
  python scripts/update.py --file x.xml # utilise un fichier local (test)
"""
import argparse, datetime as dt, gzip, io, json, os, re, sys, unicodedata, urllib.request, zipfile
from xml.etree.ElementTree import iterparse
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
SOURCES = [
    "https://xmltvfr.fr/xmltv/xmltv_tnt.xml.gz",
    "https://xmltvfr.fr/xmltv/xmltv_tnt.xml",
    "https://xmltvfr.fr/xmltv/xmltv_tnt.zip",
]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data")
DAYS_BACK, DAYS_AHEAD = 1, 10

# Numéro TNT -> identifiants XMLTV possibles (xmltvfr.fr / XML-TV-Fr)
CHANNEL_IDS = {
    1: ["TF1.fr"], 2: ["France2.fr"], 3: ["France3.fr"], 4: ["France4.fr"], 5: ["France5.fr"],
    6: ["M6.fr"], 7: ["Arte.fr"], 8: ["LaChaineParlementaire.fr", "LCP.fr", "PublicSenat.fr"],
    9: ["W9.fr"], 10: ["TMC.fr"], 11: ["TFX.fr"], 12: ["Gulli.fr"], 13: ["BFMTV.fr"],
    14: ["CNews.fr", "CNEWS.fr"], 15: ["LCI.fr"], 16: ["FranceInfo.fr", "franceinfo.fr"],
    17: ["CStar.fr", "CSTAR.fr"], 18: ["T18.fr"], 19: ["NOVO19.fr"], 20: ["TF1SeriesFilms.fr"],
    21: ["LEquipe21.fr", "LEquipe.fr"], 22: ["6ter.fr"], 23: ["Numero23.fr", "RMCStory.fr"],
    24: ["RMCDecouverte.fr"], 25: ["Cherie25.fr", "RMCLife.fr"], 26: ["ParisPremiere.fr"],
}
# Secours : correspondance par nom affiché si un identifiant change
NAMES = {
    "tf1": 1, "france2": 2, "france3": 3, "france4": 4, "france5": 5, "m6": 6, "arte": 7,
    "lcp": 8, "lcppublicsenat": 8, "lachaineparlementaire": 8, "w9": 9, "tmc": 10, "tfx": 11,
    "gulli": 12, "bfmtv": 13, "cnews": 14, "lci": 15, "franceinfo": 16, "cstar": 17, "t18": 18,
    "novo19": 19, "tf1seriesfilms": 20, "lequipe": 21, "6ter": 22, "rmcstory": 23,
    "rmcdecouverte": 24, "rmclife": 25, "cherie25": 25, "parispremiere": 26,
}

def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)

def fetch_bytes():
    last = None
    for url in SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "programme-tnt/1.0 (GitHub Actions)"})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            print(f"Téléchargé : {url} ({len(data)//1024} Ko)")
            return data
        except Exception as e:
            print(f"Échec {url} : {e}", file=sys.stderr)
            last = e
    raise SystemExit(f"Impossible de télécharger le guide : {last}")

def open_xml(data):
    if data[:2] == b"\x1f\x8b":
        return io.BytesIO(gzip.decompress(data))
    if data[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(data))
        name = next(n for n in z.namelist() if n.endswith(".xml"))
        return io.BytesIO(z.read(name))
    return io.BytesIO(data)

def parse_time(s):
    # "20261109211000 +0100"
    s = (s or "").strip()
    m = re.match(r"(\d{14})\s*([+-]\d{4})?", s)
    if not m:
        return None
    t = dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    if m.group(2):
        sign = 1 if m.group(2)[0] == "+" else -1
        off = dt.timedelta(hours=int(m.group(2)[1:3]), minutes=int(m.group(2)[3:5])) * sign
        t = t.replace(tzinfo=dt.timezone(off))
    else:
        t = t.replace(tzinfo=PARIS)
    return int(t.timestamp())

def text(el, tag):
    c = el.find(tag)
    return (c.text or "").strip() if c is not None and c.text else ""

def short(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    args = ap.parse_args()
    data = open(args.file, "rb").read() if args.file else fetch_bytes()

    id2num = {cid: num for num, ids in CHANNEL_IDS.items() for cid in ids}
    now = dt.datetime.now(PARIS)
    first_day = (now - dt.timedelta(days=DAYS_BACK)).date()
    last_day = (now + dt.timedelta(days=DAYS_AHEAD)).date()
    raw = {}  # num -> {identifiant XMLTV -> [programmes]}

    for _, el in iterparse(open_xml(data), events=("end",)):
        if el.tag == "channel":
            cid = el.get("id")
            if cid not in id2num:
                for dn in el.findall("display-name"):
                    num = NAMES.get(norm(dn.text))
                    if num:
                        id2num[cid] = num
                        break
            el.clear()
        elif el.tag == "programme":
            cid = el.get("channel")
            num = id2num.get(cid)
            if num:
                s, e = parse_time(el.get("start")), parse_time(el.get("stop"))
                if s:
                    e = e or s + 1800
                    cats = [c.text.strip() for c in el.findall("category") if c.text]
                    ep = el.find("episode-num[@system='onscreen']")
                    item = {"s": s, "e": e, "t": text(el, "title") or "Programme",
                            "c": cats[0] if cats else ""}
                    st = text(el, "sub-title")
                    if st: item["st"] = short(st, 120)
                    d = text(el, "desc")
                    if d: item["d"] = short(d, 320)
                    if ep is not None and ep.text: item["ep"] = ep.text.strip()
                    if el.find("new") is not None or el.find("premiere") is not None: item["n"] = 1
                    if el.find("live") is not None: item["l"] = 1
                    raw.setdefault(num, {}).setdefault(cid, []).append(item)
            el.clear()

    # Une seule source par chaîne : l'identifiant officiel en priorité, sinon le plus fourni
    per_day, found = {}, set()
    for num, by_id in raw.items():
        pref = [c for c in CHANNEL_IDS.get(num, []) if by_id.get(c)]
        cid = pref[0] if pref else max(by_id, key=lambda c: len(by_id[c]))
        for item in by_id[cid]:
            a = dt.datetime.fromtimestamp(item["s"], PARIS).date()
            b = dt.datetime.fromtimestamp(max(item["s"], item["e"] - 1), PARIS).date()
            day = a
            while day <= b:
                if first_day <= day <= last_day:
                    per_day.setdefault(day.isoformat(), {}).setdefault(str(num), []).append(item)
                day += dt.timedelta(days=1)
        found.add(num)

    if not per_day:
        raise SystemExit("Aucun programme trouvé : le format du guide a peut-être changé.")

    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        if re.match(r"\d{4}-\d{2}-\d{2}\.json$", f):
            os.remove(os.path.join(OUT, f))
    days = sorted(per_day)
    for day in days:
        chans = per_day[day]
        for k in chans:
            chans[k].sort(key=lambda x: x["s"])
        with open(os.path.join(OUT, f"{day}.json"), "w", encoding="utf-8") as fh:
            json.dump(chans, fh, ensure_ascii=False, separators=(",", ":"))
    index = {"updated": now.isoformat(timespec="minutes"), "days": days,
             "channels": sorted(found), "source": "xmltvfr.fr"}
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False)
    missing = [n for n in range(1, 27) if n not in found]
    print(f"{len(days)} jours écrits, {len(found)} chaînes trouvées." + (f" Absentes : {missing}" if missing else ""))

if __name__ == "__main__":
    main()
