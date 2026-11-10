"""Outils partagés : téléchargement, cache, bandes-annonces YouTube, traduction en français."""
import hashlib, html, json, os, re, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(ROOT, "data", "cache.json")
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/124.0 Safari/537.36", "Accept-Language": "fr-FR,fr;q=0.9"}

# ------------------------------------------------------------------ réseau
def get(url, headers=None, timeout=60, data=None):
    req = urllib.request.Request(url, headers={**BROWSER, **(headers or {})}, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def get_json(url, headers=None, timeout=60, data=None):
    return json.loads(get(url, headers, timeout, data))

def post_json(url, payload, headers=None, timeout=60):
    return get_json(url, {"Content-Type": "application/json", **(headers or {})}, timeout,
                    json.dumps(payload).encode())

def safe(fn, *a, default=None, **k):
    try:
        return fn(*a, **k)
    except Exception as e:
        print(f"  ! {getattr(fn, '__name__', 'appel')} : {str(e)[:160]}", file=sys.stderr)
        return default

# ------------------------------------------------------------------ texte
def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

def same_title(a, b):
    a, b = norm(a), norm(b)
    return bool(a) and bool(b) and (a == b or (len(a) > 3 and a in b) or (len(b) > 3 and b in a))

def short(s, n=380):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"

def strip_html(s):
    s = re.sub(r"<(br|/p|/li)[^>]*>", " ", s or "", flags=re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()

FR_WORDS = set("le la les un une des du de et est dans pour sur avec qui que en au aux son sa ses il elle ils elles "
               "pas plus mais ce cette ces leur lors après avant être sont été fait entre deux tout tous".split())
EN_WORDS = set("the a an and is in of to with for on his her their who that this when after from are was by "
               "as at be it its into they she he them while must".split())

def looks_french(s):
    words = re.findall(r"[a-zàâçéèêëîïôûùüÿœ']+", (s or "").lower())
    if len(words) < 4:
        return True
    fr = sum(w in FR_WORDS for w in words)
    en = sum(w in EN_WORDS for w in words)
    return fr >= en

# ------------------------------------------------------------------ cache persistant (data/cache.json)
class Cache:
    def __init__(self):
        try:
            self.d = json.load(open(CACHE_FILE, encoding="utf-8"))
        except Exception:
            self.d = {}
        for k in ("yt", "tr", "img"):
            self.d.setdefault(k, {})
        self.new_lookups = 0
    def save(self, limit=4000):
        for k, v in self.d.items():
            if len(v) > limit:
                self.d[k] = dict(list(v.items())[-limit:])
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump(self.d, fh, ensure_ascii=False, separators=(",", ":"))

CACHE = Cache()

# ------------------------------------------------------------------ YouTube (sans clé)
def _yt_search(query):
    url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query, "sp": "EgIQAQ=="})
    page = get(url, {"Cookie": "CONSENT=YES+cb; SOCS=CAI"}, timeout=30).decode("utf-8", "ignore")
    m = re.search(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", page, re.S)
    out = []
    if m:
        def walk(o):
            if isinstance(o, dict):
                if "videoRenderer" in o:
                    v = o["videoRenderer"]
                    title = "".join(r.get("text", "") for r in (v.get("title") or {}).get("runs", []))
                    if v.get("videoId"):
                        out.append((v["videoId"], title))
                for x in o.values():
                    walk(x)
            elif isinstance(o, list):
                for x in o:
                    walk(x)
        walk(json.loads(m.group(1)))
    else:
        out = [(i, "") for i in dict.fromkeys(re.findall(r'"videoId":"([\w-]{11})"', page))]
    return out[:12]

def trailer(title, year="", extra="", max_new=400):
    """Identifiant de la bande-annonce YouTube la plus pertinente (titre + année), ou None."""
    if not title:
        return None
    query = " ".join(x for x in (title, extra, str(year or ""), "bande annonce") if x).strip()
    key = norm(query)
    if key in CACHE.d["yt"]:
        return CACHE.d["yt"][key] or None
    if CACHE.new_lookups >= max_new:
        return None
    CACHE.new_lookups += 1
    results = safe(_yt_search, query, default=[]) or []
    time.sleep(0.4)
    want = [w for w in norm(title).split() if len(w) > 2] or norm(title).split()
    best, best_score = None, -1
    for rank, (vid, vt) in enumerate(results):
        t = norm(vt)
        score = 0
        if want and all(w in t for w in want): score += 4
        elif want and any(w in t for w in want): score += 1
        if re.search(r"bande annonce|trailer|teaser", t): score += 3
        if year and str(year) in t: score += 2
        if re.search(r"\b(vf|vostfr|francais|officiel)\b", t): score += 1
        if re.search(r"\b(reaction|review|critique|explained|ending|resume|recap)\b", t): score -= 4
        score -= rank * 0.3
        if score > best_score:
            best, best_score = vid, score
    vid = best if best_score >= 3 else None
    CACHE.d["yt"][key] = vid or ""
    return vid

def yt_thumb(vid):
    return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if vid else None

# ------------------------------------------------------------------ traduction (sans clé)
def _gtx(text):
    url = "https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode(
        {"client": "gtx", "sl": "auto", "tl": "fr", "dt": "t", "q": text})
    data = get_json(url, timeout=20)
    return "".join(part[0] for part in data[0] if part and part[0])

def _mymemory(text):
    url = "https://api.mymemory.translated.net/get?" + urllib.parse.urlencode({"q": text[:480], "langpair": "en|fr"})
    data = get_json(url, timeout=20)
    return (data.get("responseData") or {}).get("translatedText") or ""

def to_french(text):
    """Renvoie le texte en français (traduit si besoin, avec cache)."""
    if not text or looks_french(text):
        return text
    key = hashlib.md5(text.encode()).hexdigest()
    if key in CACHE.d["tr"]:
        return CACHE.d["tr"][key]
    fr = safe(_gtx, text) or safe(_mymemory, text) or ""
    time.sleep(0.3)
    if fr and looks_french(fr):
        CACHE.d["tr"][key] = fr
        return fr
    return text
