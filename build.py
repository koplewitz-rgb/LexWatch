import os, re, yaml, requests, feedparser
from datetime import datetime, timedelta
from dateutil import parser as dateparser
from jinja2 import Template

# ------------ helpers ------------
STOP = set(("the of a an to in for and or on at from with by over under about into after before as via israel israeli jerusalem gaza west bank"))

def read_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

UA = {"User-Agent": "LexWatchPages/1.0 (+https://github.com/)"}

def parse_published(e):
    dt = None
    if getattr(e, "published_parsed", None):
        try:
            dt = datetime(*e.published_parsed[:6])
        except Exception:
            dt = None
    if not dt:
        try:
            dt = dateparser.parse(getattr(e, "published", "") or getattr(e, "updated", ""))
        except Exception:
            dt = None
    return dt

def domain_of(url):
    try:
        return requests.utils.urlparse(url).netloc.lower()
    except Exception:
        return ""

def normalize_title(t):
    toks = re.findall(r"[A-Za-z]{3,}", (t or ""))
    toks = [w.lower() for w in toks if w.lower() not in STOP]
    return " ".join(toks[:10]) or (t or "").lower()

def topic_key(item):
    base = normalize_title(item.get("title",""))
    return f"{item.get('bucket','Other')}|{base[:80]}"

def fetch_rss(url, timeout=(10,15)):
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        r.raise_for_status()
        p = feedparser.parse(r.content)
        out = []
        for e in p.entries:
            pd = parse_published(e)
            out.append({
                "title": getattr(e, "title", ""),
                "link": getattr(e, "link", ""),
                "summary": getattr(e, "summary", ""),
                "published": getattr(e, "published", ""),
                "published_dt": pd.isoformat() if pd else "",
                "domain": domain_of(getattr(e, "link", "")),
                "source": url,
            })
        return out
    except Exception as ex:
        return [{
            "title": f"[ERROR fetching] {url}",
            "link": "",
            "summary": str(ex),
            "published": "",
            "published_dt": "",
            "domain": "",
            "source": url
        }]

def contains_any(text, terms):
    t = (text or "").lower()
    return any(x.lower() in t for x in terms)

def context_score(text, terms):
    t = (text or "").lower()
    return sum(1 for c in terms if c.lower() in t)

def israel_related(item, israel_terms):
    text = f"{item.get('title','')} {item.get('summary','')}"
    return contains_any(text, israel_terms)

def assign_bucket(item):
    t = (f"{item.get('title','')} {item.get('summary','')}").lower()
    buckets = [
        ("ICJ / Contentious & Advisory", ["icj","international court of justice","genocide convention"]),
        ("ICC / Prosecutor & Proceedings", ["icc","icc prosecutor","office of the prosecutor","war crimes","crimes against humanity"]),
        ("Law of the Sea / UNCLOS / EEZ / Innocent Passage", ["unclos","eez","innocent passage","law of the sea","maritime"]),
        ("Settlements / Occupation Law", ["settlements","west bank","occupation","ihl","ihrl","jerusalem"]),
        ("ISDS / Investment Arbitration", ["icsid","investment arbitration","bit","uncitral","arbitration"]),
        ("AI & International Law", ["artificial intelligence"," ai ","autonomous weapons","laws","ai governance","article 36","cyber norms"]),
    ]
    best, score = "Other", -1
    for name, terms in buckets:
        s = sum(1 for w in terms if w in t)
        if s > score:
            best, score = name, s
    return best

def wiki_summary(name):
    api = "https://en.wikipedia.org/api/rest_v1/page/summary/" + requests.utils.quote(name)
    try:
        r = requests.get(api, headers=UA, timeout=(6,10))
        if r.status_code != 200:
            return None
        j = r.json()
        return {
            "name": name,
            "description": j.get("description") or "",
            "summary": j.get("extract") or "",
            "source": j.get("content_urls",{}).get("desktop",{}).get("page","")
        }
    except Exception:
        return None

def apply_filters(items, track_terms, context_terms, israel_terms, min_ctx):
    out = []
    for it in items:
        text = f"{it.get('title','')} {it.get('summary','')}"
        if not contains_any(text, track_terms):
            continue
        if context_score(text, context_terms) < min_ctx:
            continue
        if not israel_related(it, israel_terms):
            continue
        it["bucket"] = assign_bucket(it)
        out.append(it)
    return out

# ------------ main ------------
def main():
    cfg = read_yaml("config.yaml")
    sources = list(set(cfg.get("sources", [])))
    blogs = list(set(cfg.get("blogs", [])))
    track_terms   = list(set(cfg.get("track_terms", []) + cfg.get("ai_terms", [])))
    context_terms = cfg.get("context_terms", [])
    israel_terms  = cfg.get("israel_terms", ["Israel"])
    min_ctx       = int(cfg.get("min_context_score", 3))  # STRONGER default
    top_n         = int(cfg.get("report_top_n", 80))
    recent_days   = int(cfg.get("recent_days", 7))
    min_topic     = int(cfg.get("min_topic_mentions", 2))
    block         = set((d.strip().lower() for d in cfg.get("source_blocklist", [])))

    feed_items, blog_items = [], []
    for u in sources:
        feed_items += fetch_rss(u)
    for b in blogs:
        blog_items += fetch_rss(b)

    # Initial filters
    feed_f = apply_filters(feed_items, track_terms, context_terms, israel_terms, min_ctx)
    blog_f = apply_filters(blog_items, track_terms, context_terms, israel_terms, min_ctx)

    # Recent only (≤ recent_days)
    cutoff = datetime.utcnow() - timedelta(days=recent_days)
    def is_recent(it):
        try:
            if it.get("published_dt"):
                return dateparser.parse(it["published_dt"]) >= cutoff
            return True  # allow undated
        except Exception:
            return True

    feed_f = [it for it in feed_f if is_recent(it)]
    blog_f = [it for it in blog_f if is_recent(it)]

    # Block noisy domains
    if block:
        feed_f = [it for it in feed_f if it.get("domain","") not in block]
        blog_f = [it for it in blog_f if it.get("domain","") not in block]

    # Dedupe (by normalized title + domain)
    seen = set()
    def dedupe(items):
        out = []
        for it in items:
            key = (normalize_title(it.get("title","")), it.get("domain",""))
            if key in seen:
                continue
            seen.add(key)
            out.append(it)
        return out

    feed_f = dedupe(feed_f)
    blog_f = dedupe(blog_f)

    # Ongoing discussions: require >= min_topic per topic_key across feeds+blogs
    all_items = feed_f + blog_f
    for it in all_items:
        it["bucket"] = assign_bucket(it)
    counts = {}
    for it in all_items:
        k = topic_key(it)
        counts[k] = counts.get(k, 0) + 1
    ongoing = [it for it in all_items if counts[topic_key(it)] >= min_topic]
    final_items = ongoing[: top_n]
# ---- Fallback if nothing matched (widen the net) ----
fallback_used = False
if len(final_items) == 0:
    fallback_used = True
    # widen recency, loosen thresholds
    fallback_recent_days = max(14, cfg.get("recent_days", 7))
    cutoff_fb = datetime.utcnow() - timedelta(days=fallback_recent_days)

    def is_recent_fb(it):
        try:
            if it.get("published_dt"):
                return dateparser.parse(it["published_dt"]) >= cutoff_fb
            return True
        except Exception:
            return True

    # allow singletons (min_topic=1) and slightly looser context (min_ctx-1)
    min_ctx_fb = max(1, int(cfg.get("min_context_score", 2)) - 1)
    min_topic_fb = 1

    # re-filter from the already filtered stage (feed_f/blog_f) but with newer rules
    feed_fb = [it for it in feed_f if is_recent_fb(it)]
    blog_fb = [it for it in blog_f if is_recent_fb(it)]
    all_fb = feed_fb + blog_fb

    # recount topics
    counts_fb = {}
    for it in all_fb:
        k = topic_key(it)
        counts_fb[k] = counts_fb.get(k, 0) + 1
    ongoing_fb = [it for it in all_fb if counts_fb[topic_key(it)] >= min_topic_fb]

    final_items = ongoing_fb[: top_n]

    # expose fallback params for the template
    recent_days = fallback_recent_days
    min_topic = min_topic_fb

    # People to Watch (from final items)
    names = set()
    cap = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+){1,2})\b")
    for it in final_items:
        for m in cap.findall(it.get("title","")):
            names.add(m)
    bios = []
    for n in list(names)[:12]:
        s = wiki_summary(n)
        if s and (len(s["summary"])>50 or len(s["description"])>0):
            bios.append(s)

    # Group by bucket
    by_bucket = {}
    for it in final_items:
        by_bucket.setdefault(it["bucket"], []).append(it)

    # Hot Topics list
    topic_counts = {}
    for it in final_items:
        k = topic_key(it)
        topic_counts[k] = topic_counts.get(k, 0) + 1
    hot_topics = sorted(topic_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
    hot_readable = []
    for k, c in hot_topics:
        bucket, frag = k.split("|", 1)
        hot_readable.append({"bucket": bucket, "fragment": frag, "count": c})

    # Render
    template = Template("""
<!doctype html><html><head>
<meta charset="utf-8">
<title>LexWatch — Israel & International Law</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:980px;margin:2rem auto;padding:0 1rem;line-height:1.5}
h1{font-size:1.8rem;margin:0 0 1rem}
h2{margin-top:2rem}
.card{border:1px solid #ddd;border-radius:12px;padding:1rem;margin:.5rem 0}
.badge{display:inline-block;background:#eef;padding:.2rem .5rem;border-radius:6px;font-size:.8rem;margin-left:.5rem}
.small{color:#666;font-size:.9rem}
.list li{margin:.25rem 0}
.header{display:flex;justify-content:space-between;align-items:center}
a{color:#0645ad;text-decoration:none}
a:hover{text-decoration:underline}
</style>
</head><body>
<div class="header">
  <h1>LexWatch — Israel & International Law</h1>
  <div class="small">{{ now }}</div>
</div>

<h2>Highlights</h2>
{% if final_count == 0 %}
<div class="card">No items matched the filters for the last {{ recent_days }} days.</div>
{% else %}
{% if fallback_used %}
<div class="card"><strong>Fallback mode:</strong> showing a wider window and looser threshold (to surface near-misses).</div>
{% endif %}
<div class="card">

    <li>Window: last {{ recent_days }} days</li>
    <li>Total items after filters: {{ final_count }}</li>
    <li>Ongoing-discussion threshold: {{ min_topic }}</li>
  </ul>
</div>

<h2>Hot Topics (last {{ recent_days }} days)</h2>
{% for ht in hot_readable %}
  <div class="card">
    <strong>{{ ht.bucket }}</strong> — {{ ht.fragment }} <span class="badge">{{ ht.count }}</span>
  </div>
{% endfor %}
{% endif %}

<h2>Topic Buckets</h2>
{% for bucket, items in buckets.items() %}
  {% if items %}
  <h3>{{ bucket }} <span class="badge">{{ items|length }}</span></h3>
  {% for it in items %}
    <div class="card">
      <div><strong><a href="{{ it.link }}" target="_blank" rel="noopener">{{ it.title }}</a></strong></div>
      <div class="small">{{ it.published or "" }} · Source: {{ it.source }}</div>
      {% if it.summary %}<div class="small">{{ it.summary|safe }}</div>{% endif %}
    </div>
  {% endfor %}
  {% endif %}
{% endfor %}

{% if bios %}
<h2>People to Watch (auto-verified)</h2>
{% for b in bios %}
  <div class="card">
    <div><strong>{{ b.name }}</strong> — {{ b.description }}</div>
    <div class="small">{{ b.summary }}</div>
    {% if b.source %}<div class="small"><a href="{{ b.source }}" target="_blank" rel="noopener">source</a></div>{% endif %}
  </div>
{% endfor %}
{% endif %}

<footer class="small" style="margin-top:3rem">
Generated by GitHub Actions (daily, Asia/Jerusalem). Configure via <code>config.yaml</code>.
</footer>
</body></html>
""")

    html = template.render(
    now=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    recent_days=recent_days,
    min_topic=min_topic,
    final_count=len(final_items),
    hot_readable=hot_readable,
    buckets=by_bucket,
    bios=bios,
    fallback_used=fallback_used
)

    os.makedirs("public", exist_ok=True)
    with open("public/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Done. Items=", len(final_items), "→ public/index.html")

if __name__ == "__main__":
    main()
