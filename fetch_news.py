"""
fetch_news.py
Fetches Argentine news headlines from RSS feeds, translates titles from
Spanish to English (no API key required — uses deep-translator's free
Google Translate web endpoint), categorizes each story, and maintains a
rolling 7-day window of up to 20 stories per category.
Output: docs/argentina_news.json
"""

import json
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import requests
from dateutil import parser as dateparser

# ── Optional: translation ─────────────────────────────────────────────────────
try:
    from deep_translator import GoogleTranslator
    from langdetect import detect as lang_detect, LangDetectException
    TRANSLATION_AVAILABLE = True
except ImportError:
    TRANSLATION_AVAILABLE = False
    print("[WARN] deep-translator / langdetect not installed. Titles will not be translated.")

# ── Configuration ─────────────────────────────────────────────────────────────

OUTPUT_PATH = Path("docs/argentina_news.json")
MAX_STORIES_PER_CATEGORY = 20
MAX_AGE_DAYS = 7

FEEDS = [
    {
        "source": "Clarín",
        "url": "https://www.clarin.com/rss/lo-ultimo/",
        "lang": "es",
    },
    {
        "source": "La Nación",
        "url": "https://www.lanacion.com.ar/arc/outboundfeeds/rss/?outputType=xml",
        "lang": "es",
    },
    {
        "source": "Infobae",
        "url": "https://www.infobae.com/feeds/rss/",
        "lang": "es",
    },
    {
        "source": "Página/12 — El País",
        "url": "https://www.pagina12.com.ar/arc/outboundfeeds/rss/secciones/el-pais/notas",
        "lang": "es",
    },
    {
        "source": "Página/12 — Economía",
        "url": "https://www.pagina12.com.ar/arc/outboundfeeds/rss/secciones/economia/notas",
        "lang": "es",
    },
    {
        "source": "Página/12 — El Mundo",
        "url": "https://www.pagina12.com.ar/arc/outboundfeeds/rss/secciones/el-mundo/notas",
        "lang": "es",
    },
    {
        "source": "El Cronista",
        "url": "https://www.cronista.com/files/rss/news.xml",
        "lang": "es",
    },
    {
        "source": "Perfil",
        "url": "https://www.perfil.com/feed",
        "lang": "es",
    },
]

CATEGORIES = ["Diplomacy", "Military", "Energy", "Economy", "Local Events"]

# ── Keyword maps (Spanish + English) ─────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "Diplomacy": [
        # Spanish
        r"\bdiplomat\w*\b", r"\bembajad\w*\b", r"\bcanciller\w*\b",
        r"\bcancillería\b", r"\brelaciones exteriores\b", r"\bministerio de relaciones\b",
        r"\btratado\b", r"\bacuerdo (bilateral|comercial|internacional|de paz)\b",
        r"\bsanción\w*\b", r"\bsanciones?\b", r"\bcumbre\b", r"\bsommit\b",
        r"\bnaciones unidas\b", r"\bonu\b", r"\bembajada\b", r"\bcónsul\w*\b",
        r"\bpolitica exterior\b", r"\bnegociación\w*\b", r"\bnegociaciones?\b",
        r"\bcooperación (internacional|bilateral)\b", r"\brelaciones (bilaterales|internacionales)\b",
        r"\bmercosur\b", r"\bunasur\b", r"\bcelac\b", r"\bfmi\b", r"\bg20\b",
        r"\bmilei.*(viaje|visita|reunión|cumbre|biden|trump|macron|xi|putin)\b",
        r"\bdiálogo (diplomático|político|bilateral)\b",
        r"\bvisita (oficial|de estado|presidencial)\b",
        r"\bargentina.*(eeuu|usa|estados unidos|china|rusia|brasil|unión europea|ue|reino unido)\b",
        # English (post-translation)
        r"\bdiplomat\w*\b", r"\bambassador\b", r"\btreaty\b", r"\bsanction\w*\b",
        r"\bforeign (affairs|minister|policy|relations)\b", r"\bsummit\b",
        r"\bbilateral\b", r"\bmultilateral\b", r"\bimf\b", r"\bwto\b",
        r"\bunited nations\b", r"\bconsulate\b", r"\bembassy\b",
    ],
    "Military": [
        # Spanish
        r"\bejército\b", r"\bfuerzas armadas\b", r"\bfuerza aérea\b",
        r"\barmada\b", r"\binfantería\b", r"\bdefensa (nacional|militar)?\b",
        r"\bministerio de defensa\b", r"\bsoldado\w*\b", r"\bmilitar\w*\b",
        r"\boperación (militar|conjunta|policial)\b", r"\bguerra\b",
        r"\bconflicto (armado|bélico|militar)\b", r"\bterroris\w*\b",
        r"\bseguridad (nacional|interior)\b", r"\bgendarmer\w*\b",
        r"\bprefectura naval\b", r"\binteligencia (militar|nacional)\b",
        r"\bside\b", r"\bservicios de inteligencia\b", r"\bpolicía federal\b",
        r"\bnarcotrafico\b", r"\bcrimen organizado\b",
        r"\bmalvinas\b", r"\bislas malvinas\b", r"\bsoberanía\b",
        r"\bbase (militar|naval|aérea)\b", r"\bdesfile militar\b",
        r"\barmas\b", r"\barmamento\b", r"\bexplosivo\w*\b",
        r"\bveterano\w*\b", r"\bcombate\b",
        # English
        r"\bmilitary\b", r"\bdefence\b", r"\bdefense\b", r"\bsoldier\w*\b",
        r"\btroops?\b", r"\bnavy\b", r"\barmy\b", r"\bair force\b",
        r"\bweapon\w*\b", r"\bterror\w*\b", r"\bsovereignt\w*\b",
        r"\bfalklands?\b", r"\bconflict\b",
    ],
    "Energy": [
        # Spanish
        r"\benergía\b", r"\benergías renovables\b", r"\bpetróleo\b",
        r"\bgas natural\b", r"\bgasoducto\b", r"\bpetroducto\b",
        r"\bvaca muerta\b", r"\bshale\b", r"\bhidrocarburos?\b",
        r"\bypf\b", r"\bpampa energía\b", r"\btecpetrol\b",
        r"\bnuclear\b", r"\batucha\b", r"\bcarem\b", r"\binvap\b",
        r"\belectricidad\b", r"\bred eléctrica\b", r"\btarifa\w*\b",
        r"\bcorte (de luz|eléctrico)\b", r"\bapagón\b",
        r"\bsolar\b", r"\beólica?\b", r"\bhidráulica?\b", r"\bhidroeléctric\w*\b",
        r"\bcarbón\b", r"\bcombustible\w*\b", r"\bnafta\b", r"\bprecio (del petróleo|del gas)\b",
        r"\btransición energética\b", r"\bemisiones?\b", r"\bcambio climático\b",
        r"\bpanorama energético\b", r"\bmatriz energética\b",
        # English
        r"\benergy\b", r"\boil\b", r"\bnatural gas\b", r"\bpipeline\b",
        r"\brenewable\b", r"\bnuclear\b", r"\belectricit\w*\b",
        r"\bhydrocarbon\w*\b", r"\bclimate\b", r"\bemission\w*\b",
    ],
    "Economy": [
        # Spanish
        r"\beconomía\b", r"\beconomic\w*\b", r"\bpresupuesto\b",
        r"\bpbi\b", r"\bpib\b", r"\binflación\b", r"\bdeflación\b",
        r"\btasa (de interés|de cambio|de inflación|de desempleo)\b",
        r"\bdesempleo\b", r"\bdesocupación\b", r"\bempleo\b",
        r"\bbanco central\b", r"\bbcra\b", r"\brecesión\b",
        r"\bdeuda (externa|pública|soberana)\b", r"\bfmi\b",
        r"\bpeso argentino\b", r"\bdólar (blue|oficial|paralelo|mep|ccl)?\b",
        r"\bcepo cambiario\b", r"\btipo de cambio\b", r"\bdevaluación\b",
        r"\bexportaciones?\b", r"\bimportaciones?\b", r"\bbalanza comercial\b",
        r"\bsalario\w*\b", r"\bsueldo\w*\b", r"\bparitaria\w*\b",
        r"\bcosto de vida\b", r"\bcanasta básica\b", r"\bpobreza\b",
        r"\bindignecia\b", r"\bsubsidio\w*\b", r"\btarifazo\b",
        r"\bimpuesto\w*\b", r"\bfiscal\b", r"\bdeficit\b", r"\bsuperávit\b",
        r"\bmercados?\b", r"\bbolsa\b", r"\bmerval\b", r"\bacciones?\b",
        r"\binversión\w*\b", r"\binversor\w*\b", r"\bpyme\w*\b",
        r"\bministro de economía\b", r"\bmilei.*(economía|dólar|inflación|ajuste)\b",
        r"\bcaputo\b",  # Finance Minister
        r"\blicuación\b", r"\bajuste (fiscal|económico)\b",
        # English
        r"\beconom\w*\b", r"\binflation\b", r"\bgdp\b", r"\bbudget\b",
        r"\brecession\b", r"\bexchange rate\b", r"\bdebt\b",
        r"\btariff\w*\b", r"\bexport\w*\b", r"\bimport\w*\b",
        r"\bpoverty\b", r"\bwage\w*\b", r"\bunemployment\b",
    ],
    "Local Events": [
        # Spanish
        r"\bprovincia\b", r"\bmunicip\w*\b", r"\bintendente\b", r"\bgobernador\b",
        r"\bcongreso\b", r"\bsenado\b", r"\bdiputado\w*\b", r"\blegislatura\b",
        r"\belecciones?\b", r"\bvoto\b", r"\bvotación\b", r"\bcampaña electoral\b",
        r"\bincendio\b", r"\binundación\b", r"\baccidente\b", r"\bchoque\b",
        r"\bcrimen\b", r"\bhomicidio\b", r"\bfemicidio\b", r"\brobos?\b",
        r"\bpolicía\b", r"\bjusticia\b", r"\bjuicio\b", r"\bfallo judicial\b",
        r"\bdetenido\w*\b", r"\barrestado\w*\b", r"\bpreso\b",
        r"\bescuela\b", r"\buniversidad\b", r"\bhospital\b", r"\bsalud\b",
        r"\bclima\b", r"\btormenta\b", r"\binundaciones?\b", r"\bsequía\b",
        r"\bterremoto\b", r"\btemblor\b", r"\binfraestructura\b",
        r"\btransporte\b", r"\bsubte\b", r"\bcolectivo\b", r"\btren\b",
        r"\bcultura\b", r"\bdeporte\b", r"\bfútbol\b", r"\bfestival\b",
        r"\bturismo\b", r"\bprotesta\b", r"\bmarcha\b", r"\bhuelga\b",
        r"\bparo\b", r"\bsindicato\b", r"\bsocial\b",
        r"\bbuenos aires\b", r"\bcórdoba\b", r"\brosario\b",
        r"\bsanta fe\b", r"\bmendoza\b", r"\bpatagonia\b",
        # English
        r"\bmunicip\w*\b", r"\bprovince\b", r"\belection\w*\b",
        r"\bfire\b", r"\bflood\b", r"\baccident\b", r"\bcrime\b",
        r"\bpolice\b", r"\bcourt\b", r"\bschool\b", r"\bhospital\b",
        r"\bstrike\b", r"\bprotest\b", r"\bweather\b",
    ],
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                import calendar
                return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
            except Exception:
                pass
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                dt = dateparser.parse(raw)
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return None


def is_english(text: str) -> bool:
    if not TRANSLATION_AVAILABLE or not text:
        return True
    try:
        return lang_detect(text) == "en"
    except LangDetectException:
        return True


def translate_to_english(text: str) -> str:
    """Translate Spanish text to English using deep-translator (no API key)."""
    if not TRANSLATION_AVAILABLE or not text:
        return text
    if is_english(text):
        return text
    try:
        result = GoogleTranslator(source="es", target="en").translate(text)
        return result if result else text
    except Exception as exc:
        print(f"[WARN] Translation failed: '{text[:60]}' — {exc}")
        return text


def score_category(text: str) -> str:
    text_lower = text.lower()
    scores = {cat: 0 for cat in CATEGORIES}
    for cat, patterns in CATEGORY_KEYWORDS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                scores[cat] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Local Events"


def fetch_feed(source: str, url: str, declared_lang: str) -> list[dict]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; StratagemdrivBot/1.0; "
            "+https://stratagemdrive.github.io/argentina-local/)"
        ),
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    }
    stories = []
    cutoff = now_utc() - timedelta(days=MAX_AGE_DAYS)

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as exc:
        print(f"[WARN] Could not fetch {url}: {exc}")
        return stories

    for entry in feed.entries:
        pub_dt = parse_date(entry)
        if pub_dt is None or pub_dt < cutoff:
            continue

        raw_title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not raw_title or not link:
            continue

        # Categorise on original Spanish title first (richer keywords),
        # then translate for the stored title field.
        summary_raw = entry.get("summary") or entry.get("description") or ""
        category = score_category(f"{raw_title} {summary_raw[:300]}")

        english_title = translate_to_english(raw_title)

        stories.append({
            "title":          english_title,
            "source":         source,
            "url":            link,
            "published_date": pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "category":       category,
        })

        # Small delay to avoid hammering the free translation endpoint
        if TRANSLATION_AVAILABLE and english_title != raw_title:
            time.sleep(0.25)

    return stories


def load_existing() -> dict[str, list[dict]]:
    if OUTPUT_PATH.exists():
        try:
            with OUTPUT_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "stories" in data:
                by_cat: dict[str, list[dict]] = {c: [] for c in CATEGORIES}
                for story in data["stories"]:
                    cat = story.get("category")
                    if cat in by_cat:
                        by_cat[cat].append(story)
                return by_cat
        except Exception as exc:
            print(f"[WARN] Could not parse existing JSON: {exc}")
    return {c: [] for c in CATEGORIES}


def merge_stories(
    existing: dict[str, list[dict]],
    fresh: list[dict],
) -> dict[str, list[dict]]:
    cutoff = now_utc() - timedelta(days=MAX_AGE_DAYS)

    for cat in CATEGORIES:
        existing[cat] = [
            s for s in existing[cat]
            if dateparser.parse(s["published_date"]).replace(tzinfo=timezone.utc) >= cutoff
        ]

    known_urls: dict[str, set[str]] = {
        cat: {s["url"] for s in existing[cat]} for cat in CATEGORIES
    }

    for story in fresh:
        cat = story["category"]
        if story["url"] in known_urls.get(cat, set()):
            continue
        existing[cat].append(story)
        known_urls[cat].add(story["url"])

    for cat in CATEGORIES:
        existing[cat].sort(key=lambda s: s["published_date"], reverse=True)
        existing[cat] = existing[cat][:MAX_STORIES_PER_CATEGORY]

    return existing


def write_output(by_cat: dict[str, list[dict]]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    all_stories = [s for stories in by_cat.values() for s in stories]
    payload = {
        "generated_at":  now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "country":        "Argentina",
        "total_stories":  len(all_stories),
        "categories":     CATEGORIES,
        "stories":        all_stories,
    }
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[INFO] Wrote {len(all_stories)} stories to {OUTPUT_PATH}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"[INFO] Starting Argentina news fetch at {now_utc().isoformat()}")

    fresh_stories: list[dict] = []
    for feed_cfg in FEEDS:
        print(f"[INFO] Fetching {feed_cfg['source']} → {feed_cfg['url']}")
        stories = fetch_feed(feed_cfg["source"], feed_cfg["url"], feed_cfg["lang"])
        print(f"       Found {len(stories)} recent stories")
        fresh_stories.extend(stories)

    print(f"[INFO] Total fresh stories collected: {len(fresh_stories)}")

    existing = load_existing()
    merged   = merge_stories(existing, fresh_stories)
    write_output(merged)


if __name__ == "__main__":
    main()
