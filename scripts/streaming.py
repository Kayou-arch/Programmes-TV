#!/usr/bin/env python3
"""
Onglet Streaming : écrit data/streaming.json avec
- le Top 10 Netflix en France (films et séries), d'après les chiffres officiels publiés par Netflix ;
- les nouveautés films et séries disponibles sur Netflix en France, via l'API gratuite de TMDB
  (seulement si le secret TMDB_KEY est configuré dans GitHub). TMDB ajoute aussi les affiches.

Usage : python scripts/streaming.py   (option --tsv fichier.tsv pour tester hors ligne)
"""
import argparse, csv, datetime as dt, io, json, os, re, sys, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "streaming.json")
NETFLIX_TSV = "https://www.netflix.com/tudum/top10/data/all-weeks-countries.tsv"
COUNTRY = "FR"
TMDB = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w342"
NETFLIX_PROVIDER = 8
UA = {"User-Agent": "programme-tnt/1.0 (GitHub Actions)"}

def get(url, headers=None, timeout=120):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def season_fr(show, season):
    s = (season or "").strip()
    if not s or s == "N/A":
        return ""
    if s.lower().startswith(show.lower()):
        s = s[len(show):].lstrip(" :–-")
    s = re.sub(r"\bSeason\b", "Saison", s)
    s = re.sub(r"\bLimited Series\b", "Mini-série", s)
    s = re.sub(r"\bPart\b", "Partie", s)
    s = re.sub(r"\bVolume\b", "Volume", s)
    return s

def top10(tsv_text):
    rows = [r for r in csv.DictReader(io.StringIO(tsv_text), delimiter="\t") if r.get("country_iso2") == COUNTRY]
    if not rows:
        raise SystemExit("Top 10 : aucune ligne pour la France, le format a peut-être changé.")
    week = max(r["week"] for r in rows)
    out = {"films": [], "series": []}
    for r in rows:
        if r["week"] != week:
            continue
        cat = "films" if r["category"].lower().startswith("film") else "series"
        out[cat].append({
            "rank": int(r["weekly_rank"]),
            "t": r["show_title"],
            "season": season_fr(r["show_title"], r.get("season_title")),
            "weeks": int(r.get("cumulative_weeks_in_top_10") or 1),
        })
    for k in out:
        out[k].sort(key=lambda x: x["rank"])
    return week, out

class Tmdb:
    def __init__(self, key):
        self.key = key.strip()
    def call(self, path, **params):
        params.setdefault("language", "fr-FR")
        headers = {"accept": "application/json"}
        if self.key.startswith("eyJ"):
            headers["Authorization"] = "Bearer " + self.key
        else:
            params["api_key"] = self.key
        return json.loads(get(f"{TMDB}{path}?{urllib.parse.urlencode(params)}", headers, 30))
    def card(self, it, kind):
        date = it.get("release_date") if kind == "movie" else it.get("first_air_date")
        return {
            "t": it.get("title") or it.get("name") or "",
            "o": (it.get("overview") or "")[:400],
            "p": IMG + it["poster_path"] if it.get("poster_path") else None,
            "y": (date or "")[:4],
            "date": date or "",
            "note": round(it.get("vote_average") or 0, 1),
        }
    def enrich(self, item, kind):
        try:
            res = self.call(f"/search/{kind}", query=item["t"], include_adult="false").get("results") or []
        except Exception as e:
            print(f"TMDB recherche « {item['t']} » : {e}", file=sys.stderr)
            return
        if res:
            c = self.card(res[0], kind)
            item["t_fr"] = c["t"]
            item.update({k: c[k] for k in ("o", "p", "y") if c[k]})
    def news(self, kind):
        today = dt.date.today()
        field = "primary_release_date" if kind == "movie" else "first_air_date"
        data = self.call(f"/discover/{kind}", watch_region=COUNTRY, with_watch_providers=NETFLIX_PROVIDER,
                         with_watch_monetization_types="flatrate", sort_by="popularity.desc",
                         **{f"{field}.gte": (today - dt.timedelta(days=90)).isoformat(),
                            f"{field}.lte": today.isoformat()})
        cards = [self.card(it, kind) for it in data.get("results", []) if it.get("poster_path")]
        cards.sort(key=lambda c: c["date"], reverse=True)
        return cards[:20]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsv")
    args = ap.parse_args()
    tsv = open(args.tsv, encoding="utf-8").read() if args.tsv else get(NETFLIX_TSV).decode("utf-8")
    week, top = top10(tsv)
    result = {"updated": dt.datetime.now(PARIS).isoformat(timespec="minutes"), "week": week,
              "top10": top, "news": None, "tmdb": False}
    key = os.environ.get("TMDB_KEY", "")
    if key:
        t = Tmdb(key)
        try:
            for it in top["films"]: t.enrich(it, "movie")
            for it in top["series"]: t.enrich(it, "tv")
            result["news"] = {"films": t.news("movie"), "series": t.news("tv")}
            result["tmdb"] = True
        except Exception as e:
            print(f"TMDB indisponible : {e}", file=sys.stderr)
    else:
        print("Pas de clé TMDB : seul le Top 10 est mis à jour (pas d’affiches ni de nouveautés).")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"Streaming : semaine du {week}, {len(top['films'])} films, {len(top['series'])} séries"
          + (", nouveautés incluses." if result["news"] else "."))

if __name__ == "__main__":
    main()
