#!/usr/bin/env python3
"""
Onglet Streaming : écrit data/streaming.json pour Netflix, Prime Video et Disney+.

Sources recoupées (aucune clé nécessaire) :
- Netflix Top 10 France : chiffres officiels publiés par Netflix ;
- JustWatch : titres populaires et récents par plateforme en France, titres et résumés en français, affiches ;
- TVmaze : nouvelles séries et nouvelles saisons mises en ligne jour par jour ;
- Wikidata et Top 10 mondial Netflix : films Netflix récents ;
- IMDb (suggestions) et miniatures YouTube : affiches de secours, pour ne jamais laisser de case vide ;
- YouTube : bande-annonce (titre + année) ; Google Traduction : résumés traduits en français.
Avec le secret facultatif TMDB_KEY, TMDB sert de source supplémentaire.
"""
import argparse, csv, datetime as dt, io, json, os, re, sys, time, urllib.parse
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glob
from common import (CACHE, get, get_json, post_json, safe, norm, wkey, same_title, short, strip_html,
                    to_french, trailer, yt_thumb)

PARIS = ZoneInfo("Europe/Paris")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "streaming.json")
COUNTRY = "FR"
TODAY = dt.date.today()
YEAR = TODAY.year
PLATFORMS = {
    "netflix": {"name": "Netflix", "jw": ["nfx"], "tvmaze": ["netflix"], "tmdb": 8,
                "wd": ["Netflix"]},
    "prime":   {"name": "Prime Video", "jw": ["prv"], "tvmaze": ["prime video", "amazon"], "tmdb": 119,
                "wd": ["Prime Video", "Amazon Prime Video", "Amazon MGM Studios"]},
    "disney":  {"name": "Disney+", "jw": ["dnp"], "tvmaze": ["disney+", "disney plus"], "tmdb": 337,
                "wd": ["Disney+"]},
}

# ================================================================ Netflix Top 10 officiel
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

def netflix_tsv(name):
    return get(f"https://www.netflix.com/tudum/top10/data/{name}", timeout=240).decode("utf-8")

def netflix_top10(tsv_text):
    rows = [r for r in csv.DictReader(io.StringIO(tsv_text), delimiter="\t") if r.get("country_iso2") == COUNTRY]
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
    # films récents d’après le Top 10 (entrés depuis moins de 4 semaines)
    recent = {}
    limit = (dt.date.fromisoformat(week) - dt.timedelta(days=28)).isoformat()
    for r in rows:
        if r["week"] >= limit and r["category"].lower().startswith("film") and int(r.get("cumulative_weeks_in_top_10") or 9) <= 2:
            recent.setdefault(r["show_title"], r["week"])
    return week, out, recent

def netflix_global_recent():
    rows = csv.DictReader(io.StringIO(netflix_tsv("all-weeks-global.tsv")), delimiter="\t")
    limit = (TODAY - dt.timedelta(days=35)).isoformat()
    out = {}
    for r in rows:
        if r.get("week", "") >= limit and "film" in r.get("category", "").lower() \
                and int(r.get("cumulative_weeks_in_top_10") or 9) <= 2:
            out.setdefault(r["show_title"], r["week"])
    return out

# ================================================================ JustWatch
JW_URL = "https://apis.justwatch.com/graphql"
JW_QUERY = """
query Titles($country: Country!, $language: Language!, $first: Int!, $filter: TitleFilter) {
  popularTitles(country: $country, filter: $filter, first: $first, sortBy: POPULAR, sortRandomSeed: 0) {
    edges { node {
      objectType
      content(country: $country, language: $language) {
        title originalTitle originalReleaseYear originalReleaseDate shortDescription
        posterUrl(profile: S332, format: JPG)
        externalIds { imdbId }
        scoring { imdbScore }
        genres { shortName }
        productionCountries
      }
    } }
  }
}"""
# originalTitle peut ne pas exister selon les versions de l’API : requête de secours sans ce champ
JW_QUERY_SAFE = JW_QUERY.replace("originalTitle ", "").replace("productionCountries", "")

def anime_tag(genres, countries):
    """Animé / manga : animation produite au Japon."""
    if "ani" in genres and "JP" in (countries or []) and "anm" not in genres:
        genres = ["anm"] + genres
    return genres

def jw_titles(filt, first=40):
    payload = {"query": JW_QUERY, "variables": {"country": COUNTRY, "language": "fr", "first": first, "filter": filt}}
    data = post_json(JW_URL, payload, {"Origin": "https://www.justwatch.com"}, timeout=40)
    if data.get("errors"):
        payload["query"] = JW_QUERY_SAFE
        data = post_json(JW_URL, payload, {"Origin": "https://www.justwatch.com"}, timeout=40)
        if data.get("errors"):
            raise RuntimeError(str(data["errors"])[:200])
    out = []
    for e in (data.get("data") or {}).get("popularTitles", {}).get("edges", []):
        n = e.get("node") or {}
        c = n.get("content") or {}
        out.append({
            "kind": "film" if n.get("objectType") == "MOVIE" else "serie",
            "t_fr": c.get("title") or "", "t_orig": c.get("originalTitle") or "",
            "y": str(c.get("originalReleaseYear") or ""), "date": c.get("originalReleaseDate") or "",
            "o": short(c.get("shortDescription") or ""),
            "p": "https://images.justwatch.com" + c["posterUrl"] if c.get("posterUrl") else None,
            "imdb": (c.get("externalIds") or {}).get("imdbId"),
            "note": (c.get("scoring") or {}).get("imdbScore"),
            "g": anime_tag([g.get("shortName") for g in (c.get("genres") or []) if g and g.get("shortName")][:4],
                           c.get("productionCountries") or []),
        })
    time.sleep(0.3)
    return out

JW_WHERE = """
query Where($country: Country!, $language: Language!, $first: Int!, $titleFilter: TitleFilter, $offerFilter: OfferFilter!) {
  popularTitles(country: $country, filter: $titleFilter, first: $first, sortBy: POPULAR, sortRandomSeed: 0) {
    edges { node {
      objectType
      content(country: $country, language: $language) { title originalTitle originalReleaseYear }
      offers(country: $country, platform: WEB, filter: $offerFilter) {
        monetizationType standardWebURL package { clearName technicalName }
      }
    } }
  }
}"""
MONET = {"FLATRATE": "abo", "FREE": "gratuit", "ADS": "gratuit"}

def jw_where(title, kind, year=None):
    """Plateformes (abonnement ou gratuites) où le titre est disponible en France."""
    k = wkey(title) + "|" + kind
    hit = CACHE.d["where"].get(k)
    if hit and hit.get("d", "") >= (TODAY - dt.timedelta(days=3)).isoformat():
        return hit["o"]
    payload = {"query": JW_WHERE, "variables": {
        "country": COUNTRY, "language": "fr", "first": 5, "offerFilter": {"bestOnly": True},
        "titleFilter": {"searchQuery": title, "objectTypes": ["MOVIE" if kind == "film" else "SHOW"],
                        "includeTitlesWithoutUrl": True}}}
    data = post_json(JW_URL, payload, {"Origin": "https://www.justwatch.com"}, timeout=40)
    time.sleep(0.3)
    if data.get("errors"):
        raise RuntimeError(str(data["errors"])[:200])
    offers = []
    for e in (data.get("data") or {}).get("popularTitles", {}).get("edges", []):
        n = e.get("node") or {}
        c = n.get("content") or {}
        if not (same_title(c.get("title", ""), title) or same_title(c.get("originalTitle") or "", title)):
            continue
        if year and c.get("originalReleaseYear") and abs(int(c["originalReleaseYear"]) - int(year)) > 1:
            continue
        seen = set()
        for o in n.get("offers") or []:
            m = MONET.get(o.get("monetizationType"))
            name = ((o.get("package") or {}).get("clearName") or "").strip()
            if m and name and name not in seen:
                seen.add(name)
                offers.append({"n": name, "u": o.get("standardWebURL") or "", "m": m})
        break
    offers = offers[:5]
    CACHE.d["where"][k] = {"d": TODAY.isoformat(), "o": offers}
    return offers

def where_for_tv(max_lookups=220):
    """Pour les films et séries diffusés à la TV : où les regarder aussi en streaming."""
    titles = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "20??-??-??.json"))):
        try:
            day = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for progs in day.values():
            for p in progs:
                c = (p.get("c") or "").lower()
                if re.search(r"documentaire|magazine|réalité|jeu|journal|information|jeunesse|sport", c):
                    continue
                if re.search(r"séri|serie|feuilleton|saga", c):
                    kind = "serie"
                elif re.search(r"film|comédie|comedie|drame|dramatique|thriller|policier|action|aventure|western|"
                               r"horreur|fantastique|science-fiction|guerre|romance|animation", c):
                    kind = "film"
                else:
                    continue
                titles.setdefault(wkey(p["t"]), (p["t"], kind, p.get("y")))
    out, n = {}, 0
    for key, (title, kind, year) in titles.items():
        cached = CACHE.d["where"].get(wkey(title) + "|" + kind)
        if not cached or cached.get("d", "") < (TODAY - dt.timedelta(days=3)).isoformat():
            if n >= max_lookups:
                continue
            n += 1
        offers = safe(jw_where, title, kind, year, default=None)
        if offers:
            out[key] = offers
    print(f"Où regarder : {len(out)} titres TV disponibles aussi en streaming ({n} nouvelles recherches).")
    return out

def jw_find(title, kind, packages=None, year=None):
    filt = {"searchQuery": title, "objectTypes": ["MOVIE" if kind == "film" else "SHOW"], "includeTitlesWithoutUrl": True}
    if packages:
        filt["packages"] = packages
    res = safe(jw_titles, filt, 6, default=[]) or []
    for r in res:
        if same_title(r["t_fr"], title) or same_title(r["t_orig"], title):
            if not year or not r["y"] or abs(int(r["y"]) - int(year)) <= 1:
                return r
    return None

def jw_popular(packages, kind, first=10, min_year=None):
    filt = {"packages": packages, "objectTypes": ["MOVIE" if kind == "film" else "SHOW"], "includeTitlesWithoutUrl": True}
    if min_year:
        filt["releaseYear"] = {"min": min_year}
    return jw_titles(filt, first)

# ================================================================ TVmaze (séries)
TVMAZE_GENRES = {"Action": "act", "Adventure": "act", "Anime": "anm", "Comedy": "cmy", "Crime": "crm",
                 "Documentary": "doc", "Drama": "drm", "Family": "fml", "Children": "fml", "Fantasy": "fnt",
                 "History": "hst", "Horror": "hrr", "Romance": "rma", "Science-Fiction": "scf", "Thriller": "trl",
                 "Mystery": "trl", "Espionage": "trl", "War": "war", "Western": "wsn", "Music": "msc",
                 "Sports": "spt", "Supernatural": "fnt", "Medical": "drm", "Legal": "crm", "Reality": "rly"}

def tvmaze_card(show):
    img = show.get("image") or {}
    g = [TVMAZE_GENRES[x] for x in show.get("genres") or [] if x in TVMAZE_GENRES]
    if (show.get("type") or "") == "Reality": g.append("rly")
    if (show.get("type") or "") == "Documentary": g.append("doc")
    if (show.get("type") or "") == "Animation":
        g.append("anm" if (show.get("language") or "") == "Japanese" else "ani")
    if "anm" in g and "ani" not in g: g.append("ani")
    return {"p": (img.get("medium") or img.get("original") or "").replace("http://", "https://") or None,
            "o": short(strip_html(show.get("summary"))), "y": (show.get("premiered") or "")[:4],
            "note": (show.get("rating") or {}).get("average"), "g": list(dict.fromkeys(g))[:4]}

def tvmaze_lookup(name):
    try:
        return get_json("https://api.tvmaze.com/singlesearch/shows?" + urllib.parse.urlencode({"q": name}), timeout=20)
    except Exception:
        return None
    finally:
        time.sleep(0.6)

def tvmaze_series(days_back=45, days_ahead=30):
    """Premiers épisodes (nouvelle série ou saison) : mis en ligne récemment et à venir, par plateforme."""
    past = {k: [] for k in PLATFORMS}
    soon = {k: [] for k in PLATFORMS}
    seen = set()
    for i in range(-days_ahead, days_back):
        day = TODAY - dt.timedelta(days=i)
        eps = safe(get_json, f"https://api.tvmaze.com/schedule/web?date={day.isoformat()}", default=[], timeout=30) or []
        for ep in eps:
            show = (ep.get("_embedded") or {}).get("show") or {}
            wc = ((show.get("webChannel") or {}).get("name") or "").lower()
            plat = next((k for k, p in PLATFORMS.items() if any(w in wc for w in p["tvmaze"])), None)
            if not plat or ep.get("number") not in (1, None):
                continue
            key = (plat, show.get("id"), ep.get("season"))
            if key in seen:
                continue
            seen.add(key)
            s = ep.get("season") or 1
            date = ep.get("airdate") or day.isoformat()
            item = {"t": show.get("name", ""), "season": f"Saison {s}" if s > 1 else "Nouvelle série",
                    "date": date, "y": date[:4], "kind": "serie"}
            item.update({k: v for k, v in tvmaze_card(show).items() if v and k != "y"})
            (soon if date > TODAY.isoformat() else past)[plat].append(item)
        time.sleep(0.6)
    return past, soon

# ================================================================ Wikidata (films Netflix récents)
SPARQL = """
SELECT ?frLabel ?enLabel (MIN(?d) AS ?date) WHERE {
  VALUES ?name { %s }
  ?dist rdfs:label ?name .
  ?film wdt:P750 ?dist ; wdt:P577 ?d .
  FILTER NOT EXISTS { ?film wdt:P31/wdt:P279* wd:Q5398426 }
  FILTER(?d >= "%s"^^xsd:dateTime && ?d <= "%s"^^xsd:dateTime)
  OPTIONAL { ?film rdfs:label ?frLabel FILTER(LANG(?frLabel) = "fr") }
  OPTIONAL { ?film rdfs:label ?enLabel FILTER(LANG(?enLabel) = "en") }
} GROUP BY ?frLabel ?enLabel ORDER BY ?date LIMIT 80"""

def wikidata_films(names, start, end):
    """Films distribués par la plateforme (nom anglais sur Wikidata) sortis entre deux dates."""
    values = " ".join(f'"{n}"@en' for n in names)
    q = SPARQL % (values, start.isoformat() + "T00:00:00Z", end.isoformat() + "T23:59:59Z")
    data = get_json("https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": q, "format": "json"}),
                    {"Accept": "application/sparql-results+json"}, timeout=90)
    out = []
    for b in data["results"]["bindings"]:
        en = (b.get("enLabel") or {}).get("value") or ""
        fr = (b.get("frLabel") or {}).get("value") or en
        if fr and not re.match(r"^Q\d+$", fr):
            out.append({"t": en or fr, "t_fr": fr, "date": b["date"]["value"][:10], "y": b["date"]["value"][:4], "kind": "film"})
    time.sleep(1)
    return out

def wikidata_netflix_films(days=75):
    return wikidata_films(PLATFORMS["netflix"]["wd"], TODAY - dt.timedelta(days=days), TODAY)

# ================================================================ IMDb (affiches de secours)
def imdb_poster(title, year=None, kind="film"):
    q = norm(title)
    if not q:
        return None, None
    data = safe(get_json, f"https://v3.sg.media-imdb.com/suggestion/x/{urllib.parse.quote(q)}.json", default={}, timeout=20) or {}
    time.sleep(0.2)
    for d in data.get("d", []):
        if not d.get("i") or not same_title(d.get("l", ""), title):
            continue
        if kind == "film" and d.get("qid") not in (None, "movie", "tvMovie", "video"):
            continue
        if kind == "serie" and d.get("qid") not in (None, "tvSeries", "tvMiniSeries"):
            continue
        if year and d.get("y") and kind == "film" and abs(int(d["y"]) - int(year)) > 1:
            continue
        url = d["i"].get("imageUrl", "")
        if url:
            return re.sub(r"\._V1_.*\.jpg$", "._V1_UX300_.jpg", url), str(d.get("y") or "")
    return None, None

# ================================================================ TMDB (facultatif)
class Tmdb:
    def __init__(self, key): self.key = key.strip()
    def call(self, path, **params):
        params.setdefault("language", "fr-FR")
        headers = {"accept": "application/json"}
        if self.key.startswith("eyJ"): headers["Authorization"] = "Bearer " + self.key
        else: params["api_key"] = self.key
        return get_json(f"https://api.themoviedb.org/3{path}?{urllib.parse.urlencode(params)}", headers, 30)
    def find(self, title, kind):
        res = (safe(self.call, f"/search/{'movie' if kind == 'film' else 'tv'}", query=title, default={}) or {}).get("results") or []
        if not res: return None
        it = res[0]
        date = it.get("release_date") or it.get("first_air_date") or ""
        return {"t_fr": it.get("title") or it.get("name"), "o": short(it.get("overview") or ""),
                "p": "https://image.tmdb.org/t/p/w342" + it["poster_path"] if it.get("poster_path") else None, "y": date[:4]}

# ================================================================ enrichissement commun
def fill(item, src):
    if not src: return
    for k in ("t_fr", "o", "p", "y", "note", "date", "g"):
        v = src.get(k)
        if v and not item.get(k):
            item[k] = v

def enrich(item, kind, packages=None, tmdb=None):
    """Titre français, affiche, résumé, année, bande-annonce : jamais de case vide."""
    title = item.get("t") or item.get("t_fr")
    if not (item.get("t_fr") and item.get("p") and item.get("o") and item.get("g")):
        fill(item, jw_find(title, kind, packages, item.get("y") if kind == "film" else None))
    if tmdb and not (item.get("p") and item.get("o")):
        fill(item, tmdb.find(title, kind))
    if kind == "serie" and not (item.get("p") and item.get("o")):
        show = tvmaze_lookup(title)
        if show and same_title(show.get("name", ""), title):
            fill(item, {k: v for k, v in tvmaze_card(show).items() if k != "y"})
    if not item.get("p"):
        p, y = imdb_poster(title, item.get("y"), kind)
        if p: item["p"] = p
        if y and not item.get("y"): item["y"] = y
    # bande-annonce : titre français + année (+ saison pour les séries)
    season = item.get("season") if kind == "serie" and item.get("season", "").startswith("Saison") else ""
    year = item.get("y") if kind == "film" or season else ""
    vid = trailer(item.get("t_fr") or title, year, season)
    if not vid and item.get("t_fr") and item.get("t") and norm(item["t"]) != norm(item["t_fr"]):
        vid = trailer(item["t"], year, season)
    if vid:
        item["yt"] = vid
        if not item.get("p"):
            item["p"] = yt_thumb(vid)
    if item.get("o"):
        item["o"] = to_french(item["o"])
    for k in ("kind", "t_orig", "imdb", "lang"):
        item.pop(k, None)

def dedupe(items):
    seen, out = set(), []
    for it in items:
        k = norm(it.get("t_fr") or it.get("t"))
        if k and k not in seen:
            seen.add(k); out.append(it)
    return out

# ================================================================ construction par plateforme
def build(key, cfg, tmdb, tvm_new, nf_top=None, nf_recent=None, tvm_soon=None):
    print(f"— {cfg['name']}")
    pk = cfg["jw"]
    plat = {"name": cfg["name"], "official": False, "top": {"films": [], "series": []},
            "news": {"films": [], "series": []}, "soon": []}

    # Top 10
    if nf_top:
        plat["official"] = True
        plat["top"] = nf_top
    else:
        for kind, cat in (("film", "films"), ("serie", "series")):
            items = safe(jw_popular, pk, kind, 10, default=[]) or []
            plat["top"][cat] = [dict(it, rank=i + 1, t=it.get("t_orig") or it["t_fr"]) for i, it in enumerate(items)]
    for cat, kind in (("films", "film"), ("series", "serie")):
        for it in plat["top"][cat]:
            enrich(it, kind, pk, tmdb)

    # Nouveaux films : titres récents de la plateforme (JustWatch), + sources Netflix
    films = []
    recent = safe(jw_popular, pk, "film", 100, YEAR - 1, default=[]) or []
    horizon = (TODAY - dt.timedelta(days=150)).isoformat()
    for it in recent:
        if it.get("date") and horizon <= it["date"] <= TODAY.isoformat():
            films.append(dict(it, t=it.get("t_orig") or it["t_fr"]))
    if key == "netflix":
        for src in (nf_recent or {}).items():
            films.append({"t": src[0], "date": src[1], "y": src[1][:4], "kind": "film"})
    films += safe(wikidata_films, cfg["wd"], TODAY - dt.timedelta(days=75), TODAY, default=[]) or []
    if len(films) < 12:  # complète avec les films récents les plus populaires
        for it in recent:
            if it.get("y") and int(it["y"]) >= YEAR - 1:
                films.append(dict(it, t=it.get("t_orig") or it["t_fr"]))
    films = dedupe(films)[:30]
    for it in films:
        enrich(it, "film", pk, tmdb)
    films.sort(key=lambda x: x.get("date") or x.get("y") or "", reverse=True)
    plat["news"]["films"] = films

    # Nouvelles séries et saisons : TVmaze, complété par JustWatch
    series = tvm_new.get(key, [])[:25]
    if len(series) < 10:
        for it in safe(jw_popular, pk, "serie", 40, YEAR - 1, default=[]) or []:
            series.append(dict(it, t=it.get("t_orig") or it["t_fr"], season="Nouveauté"))
    series = dedupe(series)[:25]
    for it in series:
        enrich(it, "serie", pk, tmdb)
    series.sort(key=lambda x: x.get("date") or x.get("y") or "", reverse=True)
    plat["news"]["series"] = series

    # Animés / mangas populaires sur la plateforme (animation japonaise)
    anime = safe(jw_titles, {"packages": pk, "genres": ["ani"], "productionCountries": ["JP"],
                             "objectTypes": ["SHOW", "MOVIE"], "includeTitlesWithoutUrl": True}, 30, default=[]) or []
    anime = dedupe([dict(it, t=it.get("t_orig") or it["t_fr"]) for it in anime])
    for it in anime:
        it["k"] = it.get("kind", "serie")
        if "anm" not in (it.get("g") or []):
            it["g"] = ["anm"] + (it.get("g") or [])
        enrich(it, it["k"], pk, tmdb)
    plat["anime"] = anime

    # Top 30 populaire (films et séries) : réserve de titres pour les Favoris
    plat["popular"] = {"films": [], "series": []}
    for kind, cat in (("film", "films"), ("serie", "series")):
        pop = safe(jw_popular, pk, kind, 30, default=[]) or []
        pop = dedupe([dict(it, t=it.get("t_orig") or it["t_fr"], rank=i + 1) for i, it in enumerate(pop)])
        for it in pop:
            enrich(it, kind, pk, tmdb)
        plat["popular"][cat] = pop

    # Bientôt : films (Wikidata) et séries / saisons (TVmaze) annoncés dans les 45 prochains jours
    soon = [dict(it, kind="film") for it in (safe(wikidata_films, cfg["wd"], TODAY + dt.timedelta(days=1),
                                                  TODAY + dt.timedelta(days=45), default=[]) or [])]
    soon += [dict(it) for it in (tvm_soon or {}).get(key, [])]
    soon = dedupe(soon)
    soon.sort(key=lambda x: x.get("date") or "")
    soon = soon[:30]
    for it in soon:
        kind = it.get("kind", "film")
        enrich(it, kind, None, tmdb)
        it["k"] = kind
    plat["soon"] = soon
    n = sum(1 for g in (plat["top"], plat["news"]) for c in g.values() for it in c)
    ni = sum(1 for g in (plat["top"], plat["news"]) for c in g.values() for it in c if it.get("p"))
    print(f"  {n} titres, {ni} avec affiche, {len(films)} nouveaux films, {len(series)} nouvelles séries, {len(soon)} à venir")
    return plat

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsv")
    ap.add_argument("--only", help="netflix, prime ou disney")
    args = ap.parse_args()
    key = os.environ.get("TMDB_KEY", "").strip()
    tmdb = Tmdb(key) if key else None

    tsv = open(args.tsv, encoding="utf-8").read() if args.tsv else safe(netflix_tsv, "all-weeks-countries.tsv")
    week, nf_top, nf_recent = (safe(netflix_top10, tsv, default=None) if tsv else None) or (None, None, {})
    if not args.tsv:
        nf_recent.update(safe(netflix_global_recent, default={}) or {})
    tvm_new, tvm_soon = safe(tvmaze_series, default=({}, {})) or ({}, {})

    result = {"updated": dt.datetime.now(PARIS).isoformat(timespec="minutes"), "week": week, "platforms": {}}
    for k, cfg in PLATFORMS.items():
        if args.only and k != args.only:
            continue
        result["platforms"][k] = safe(build, k, cfg, tmdb, tvm_new,
                                      nf_top if k == "netflix" else None, nf_recent if k == "netflix" else None, tvm_soon,
                                      default={"name": cfg["name"], "official": False,
                                               "top": {"films": [], "series": []}, "news": {"films": [], "series": []}})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, separators=(",", ":"))
    CACHE.save()
    where = safe(where_for_tv, default={}) or {}
    with open(os.path.join(ROOT, "data", "where.json"), "w", encoding="utf-8") as fh:
        json.dump({"updated": result["updated"], "titles": where}, fh, ensure_ascii=False, separators=(",", ":"))
    CACHE.save()
    print("Streaming terminé.")

if __name__ == "__main__":
    main()
