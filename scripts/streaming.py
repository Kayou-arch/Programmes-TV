#!/usr/bin/env python3
"""
Onglet Streaming : écrit data/streaming.json.

Sans aucune clé, en recoupant plusieurs sources ouvertes :
- Top 10 Netflix France : chiffres officiels publiés par Netflix ;
- nouvelles séries et nouvelles saisons Netflix : TVmaze (programme des plateformes) ;
- nouveaux films Netflix : Wikidata (films distribués par Netflix, avec leur date de sortie) ;
- affiches et résumés : TVmaze pour les séries, Wikipédia (français puis anglais) pour les films.
Avec le secret facultatif TMDB_KEY, TMDB est utilisé en priorité (affiches et résumés en français).

Usage : python scripts/streaming.py   (--tsv fichier.tsv pour tester le Top 10 hors ligne)
"""
import argparse, csv, datetime as dt, html, io, json, os, re, sys, time, unicodedata, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "streaming.json")
NETFLIX_TSV = "https://www.netflix.com/tudum/top10/data/all-weeks-countries.tsv"
COUNTRY = "FR"
UA = {"User-Agent": "programme-tnt/1.1 (https://github.com/ ; appli perso de programmes TV)"}
NEWS_DAYS = 45

# ---------------------------------------------------------------- outils
def get(url, headers=None, timeout=60):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def get_json(url, headers=None, timeout=60):
    return json.loads(get(url, headers, timeout))

def safe(fn, *a, default=None, **k):
    try:
        return fn(*a, **k)
    except Exception as e:
        print(f"  ! {fn.__name__} : {e}", file=sys.stderr)
        return default

def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

def strip_html(s):
    s = re.sub(r"<(br|/p|/li)[^>]*>", " ", s or "", flags=re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()

def short(s, n=360):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"

def same_title(a, b):
    a, b = norm(a), norm(b)
    return bool(a) and bool(b) and (a == b or a in b or b in a)

# ---------------------------------------------------------------- Top 10 Netflix
def season_fr(show, season):
    s = (season or "").strip()
    if not s or s == "N/A":
        return ""
    if s.lower().startswith(show.lower()):
        s = s[len(show):].lstrip(" :–-")
    s = re.sub(r"\bSeason\b", "Saison", s)
    s = re.sub(r"\bLimited Series\b", "Mini-série", s)
    s = re.sub(r"\bPart\b", "Partie", s)
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
        out[cat].append({"rank": int(r["weekly_rank"]), "t": r["show_title"],
                         "season": season_fr(r["show_title"], r.get("season_title")),
                         "weeks": int(r.get("cumulative_weeks_in_top_10") or 1)})
    for k in out:
        out[k].sort(key=lambda x: x["rank"])
    return week, out

# ---------------------------------------------------------------- Wikipédia
def wiki_page(lang, query, title, want_image):
    params = {"action": "query", "format": "json", "formatversion": "2", "redirects": "1",
              "generator": "search", "gsrsearch": query, "gsrlimit": "3",
              "prop": "extracts|pageimages", "exintro": "1", "explaintext": "1", "exsentences": "3",
              "piprop": "thumbnail", "pithumbsize": "342"}
    data = get_json(f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params), timeout=20)
    pages = sorted((data.get("query") or {}).get("pages", []), key=lambda p: p.get("index", 99))
    for p in pages:
        base = re.sub(r"\s*\(.*?\)\s*$", "", p.get("title", ""))
        if same_title(base, title):
            return {"o": short(p.get("extract", "")), "p": (p.get("thumbnail") or {}).get("source")}
    return None

def fr_summary(item, kind):
    """Résumé en français depuis Wikipédia, prioritaire sur un résumé anglais."""
    title = item.get("t_fr") or item["t"]
    word = "film" if kind == "film" else "série télévisée"
    fr = safe(wiki_page, "fr", f"{title} {word} Netflix", title, False)
    if fr:
        if fr["o"]: item["o"] = fr["o"]
        if fr["p"] and not item.get("p"): item["p"] = fr["p"]
    time.sleep(0.2)

def wiki_enrich(item, kind, title=None, year=""):
    title = title or item.get("t_fr") or item["t"]
    word_fr, word_en = ("film", "film") if kind == "film" else ("série télévisée", "TV series")
    fr = safe(wiki_page, "fr", f"{title} {word_fr} Netflix {year}".strip(), title, False)
    if fr and fr["o"] and not item.get("o"):
        item["o"] = fr["o"]
    if fr and fr["p"] and not item.get("p"):
        item["p"] = fr["p"]
    if not item.get("p"):
        en = safe(wiki_page, "en", f"{item['t']} {word_en} Netflix {year}".strip(), item["t"], True)
        if en:
            if en["p"]: item["p"] = en["p"]
            if en["o"] and not item.get("o"): item["o"] = en["o"]
    time.sleep(0.2)

# ---------------------------------------------------------------- TVmaze (séries)
def tvmaze_show(name):
    try:
        return get_json("https://api.tvmaze.com/singlesearch/shows?" + urllib.parse.urlencode({"q": name}), timeout=20)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise

def tvmaze_card(show):
    img = (show.get("image") or {})
    return {"p": (img.get("medium") or img.get("original") or "").replace("http://", "https://") or None,
            "o": short(strip_html(show.get("summary"))), "y": (show.get("premiered") or "")[:4],
            "note": (show.get("rating") or {}).get("average")}

def tvmaze_enrich(item):
    show = safe(tvmaze_show, item["t"])
    if show and same_title(show.get("name", ""), item["t"]):
        c = tvmaze_card(show)
        for k, v in c.items():
            if v and not item.get(k):
                item[k] = v
    time.sleep(0.6)  # TVmaze : 20 requêtes / 10 s maximum

def tvmaze_new_series():
    """Premiers épisodes (nouvelle série ou nouvelle saison) mis en ligne sur Netflix ces dernières semaines."""
    today = dt.date.today()
    seen, out = set(), []
    for i in range(NEWS_DAYS):
        day = today - dt.timedelta(days=i)
        eps = safe(get_json, f"https://api.tvmaze.com/schedule/web?date={day.isoformat()}", default=[], timeout=30) or []
        for ep in eps:
            show = (ep.get("_embedded") or {}).get("show") or {}
            wc = (show.get("webChannel") or {}).get("name", "")
            if "netflix" not in wc.lower() or ep.get("number") not in (1, None):
                continue
            key = (show.get("id"), ep.get("season"))
            if key in seen:
                continue
            seen.add(key)
            c = tvmaze_card(show)
            s = ep.get("season") or 1
            out.append({"t": show.get("name", ""), "season": f"Saison {s}" if s > 1 else "Nouvelle série",
                        "date": ep.get("airdate") or day.isoformat(), **{k: v for k, v in c.items() if v}})
        time.sleep(0.6)
    out.sort(key=lambda x: x["date"], reverse=True)
    out = out[:25]
    for it in out:
        fr_summary(it, "serie")
    return out

# ---------------------------------------------------------------- Wikidata (films)
SPARQL = """
SELECT ?film ?frLabel ?enLabel (MIN(?d) AS ?date) WHERE {
  ?film wdt:P750 wd:Q907311 ; wdt:P577 ?d .
  ?film wdt:P31/wdt:P279? wd:Q11424 .
  FILTER(?d >= "%s"^^xsd:dateTime && ?d <= "%s"^^xsd:dateTime)
  OPTIONAL { ?film rdfs:label ?frLabel FILTER(LANG(?frLabel) = "fr") }
  OPTIONAL { ?film rdfs:label ?enLabel FILTER(LANG(?enLabel) = "en") }
} GROUP BY ?film ?frLabel ?enLabel ORDER BY DESC(?date) LIMIT 40
"""

def wikidata_new_films():
    today = dt.date.today()
    q = SPARQL % ((today - dt.timedelta(days=NEWS_DAYS)).isoformat() + "T00:00:00Z", today.isoformat() + "T23:59:59Z")
    data = get_json("https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": q, "format": "json"}),
                    {"Accept": "application/sparql-results+json"}, timeout=60)
    out, seen = [], set()
    for b in data["results"]["bindings"]:
        en = (b.get("enLabel") or {}).get("value") or ""
        fr = (b.get("frLabel") or {}).get("value") or en
        if not fr or re.match(r"^Q\d+$", fr) or norm(fr) in seen:
            continue
        seen.add(norm(fr))
        item = {"t": en or fr, "t_fr": fr, "date": b["date"]["value"][:10], "y": b["date"]["value"][:4]}
        wiki_enrich(item, "film", fr, item["y"])
        out.append(item)
    out.sort(key=lambda x: (bool(x.get("p")), x["date"]), reverse=True)
    out = sorted(out[:25], key=lambda x: x["date"], reverse=True)
    return out

# ---------------------------------------------------------------- TMDB (facultatif)
class Tmdb:
    IMG = "https://image.tmdb.org/t/p/w342"
    def __init__(self, key): self.key = key.strip()
    def call(self, path, **params):
        params.setdefault("language", "fr-FR")
        headers = {"accept": "application/json"}
        if self.key.startswith("eyJ"): headers["Authorization"] = "Bearer " + self.key
        else: params["api_key"] = self.key
        return get_json(f"https://api.themoviedb.org/3{path}?{urllib.parse.urlencode(params)}", headers, 30)
    def card(self, it, kind):
        date = it.get("release_date") if kind == "movie" else it.get("first_air_date")
        return {"t_fr": it.get("title") or it.get("name") or "", "o": short(it.get("overview") or ""),
                "p": self.IMG + it["poster_path"] if it.get("poster_path") else None,
                "y": (date or "")[:4], "date": date or "", "note": round(it.get("vote_average") or 0, 1) or None}
    def enrich(self, item, kind):
        res = safe(self.call, f"/search/{kind}", query=item["t"], include_adult="false", default={}) or {}
        res = res.get("results") or []
        if res:
            c = self.card(res[0], kind)
            for k in ("t_fr", "o", "p", "y", "note"):
                if c.get(k) and not item.get(k): item[k] = c[k]
    def news(self, kind):
        today = dt.date.today()
        field = "primary_release_date" if kind == "movie" else "first_air_date"
        data = self.call(f"/discover/{kind}", watch_region=COUNTRY, with_watch_providers=8,
                         with_watch_monetization_types="flatrate", sort_by="popularity.desc",
                         **{f"{field}.gte": (today - dt.timedelta(days=90)).isoformat(), f"{field}.lte": today.isoformat()})
        cards = [dict(self.card(it, kind), t=it.get("original_title") or it.get("original_name") or "")
                 for it in data.get("results", []) if it.get("poster_path")]
        cards.sort(key=lambda c: c["date"], reverse=True)
        return cards[:20]

# ---------------------------------------------------------------- principal
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsv")
    args = ap.parse_args()
    tsv = open(args.tsv, encoding="utf-8").read() if args.tsv else get(NETFLIX_TSV, timeout=180).decode("utf-8")
    week, top = top10(tsv)
    key = os.environ.get("TMDB_KEY", "").strip()
    tmdb = Tmdb(key) if key else None
    sources = ["Netflix (Top 10)"]

    print("Affiches et résumés du Top 10…")
    for it in top["series"]:
        if tmdb: tmdb.enrich(it, "tv")
        if not it.get("o"): fr_summary(it, "serie")
        tvmaze_enrich(it)
        if not it.get("p") or not it.get("o"): wiki_enrich(it, "serie")
    for it in top["films"]:
        if tmdb: tmdb.enrich(it, "movie")
        if not it.get("p") or not it.get("o"): wiki_enrich(it, "film")

    print("Nouveautés…")
    news = {"films": [], "series": []}
    if tmdb:
        news["films"] = safe(tmdb.news, "movie", default=[]) or []
        news["series"] = safe(tmdb.news, "tv", default=[]) or []
        if news["films"] or news["series"]: sources.append("TMDB")
    if not news["series"]:
        news["series"] = safe(tvmaze_new_series, default=[]) or []
        if news["series"]: sources.append("TVmaze")
    if not news["films"]:
        news["films"] = safe(wikidata_new_films, default=[]) or []
        if news["films"]: sources.append("Wikidata")
    sources += ["TVmaze", "Wikipédia"]

    result = {"updated": dt.datetime.now(PARIS).isoformat(timespec="minutes"), "week": week,
              "top10": top, "news": news, "sources": sorted(set(sources)), "tmdb": bool(tmdb)}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, separators=(",", ":"))
    n_img = sum(1 for k in top for it in top[k] if it.get("p"))
    print(f"Streaming : semaine du {week}, Top 10 avec {n_img}/{len(top['films']) + len(top['series'])} affiches, "
          f"{len(news['films'])} nouveaux films, {len(news['series'])} nouvelles séries.")

if __name__ == "__main__":
    main()
