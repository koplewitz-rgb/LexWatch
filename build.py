import os, re, yaml, requests, feedparser
from datetime import datetime
from jinja2 import Template

def read_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

UA = {"User-Agent": "LexWatchPages/1.0 (+https://github.com/)"}

def fetch_rss(url, timeout=(10,15)):
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        r.raise_for_status()
        p = feedparser.parse(r.content)
        out = []
        for e in p.entries:
            out.append({
                "title": getattr(e, "title", ""),
                "link": getattr(e, "link", ""),
                "summary": getattr(e, "summary", ""),
                "published": getattr(e, "published", ""),
                "source": url,
            })
        return out
    except Exception as ex:
        return [{
            "title": f"[ERROR fetching] {url}",
            "link": "",
            "summary": str(ex),
            "published": "",
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

def apply_filters(items, track_terms, context_terms, israel_terms, min_ctx, top_n):
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
    return out[:top_n]

def main():
    cfg = read_yaml("config.yaml")
    sources = list(set(cfg.get("sources", [])))
    blogs = list(set(cfg.get("blogs", [])))
    track_terms = list(set(cfg.get("track_terms", []) + cfg.get("ai_terms", [])))
    context_terms = cfg.get("context_terms", [])
    israel_terms = cfg.get("israel_terms", ["Israel"])
    min_ctx = int(cfg.get("min_context_score", 1))
    top_n = int(cfg.get("report_top_n", 80))

    feed_items, blog_items = [], []
    for u in sources:
        feed_items += fetch_rss(u)
    for b in blogs:
        blog_items += fetch_rss(b)

    feed_f = apply_filters(feed_items, track_terms, context_terms, israel_terms, min_ctx, top_n)
    blog_f = apply_filters(blog_items, track_terms, context_terms, israel_terms, min_ctx, top_n)

    # People to Watch (names from titles)
    names = set()
    cap = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+){1,2})\b")
    for it in (feed_f + blog_f):
        for m in cap.findall(it.get("title","")):
            names.add(m)
    bios = []
    for n in list(names)[:12]:
        s = wiki_summary(n)
        if s and (len(s["summary"])>50 or len(s["description"])>0):
            bios.append(s)

    # Buckets
    by_bucket = {}
    for it in (feed_f + blog_f):
        by_bucket.setdefault(it["bucket"], []).append(it)

    template = Template("""<!doctype html><html><head>
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

<p class="small">All items filtered to Israel and international-law signals. Buckets: ICJ · ICC · Law of the Sea · Settlements · ISDS · AI & Intl Law.</p>

<h2>Highlights</h2>
{% if feed|length + blogs|length == 0 %}
<div class="card">No items matched the filters today.</div>
{% else %}
<div class="card">
  <ul class="list">
    <li>Total items: {{ feed|length + blogs|length }}</li>
    <li>Feeds: {{ feed|length }} | Blogs: {{ blogs|length }}</li>
  </ul>
</div>
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
        feed=feed_f, blogs=blog_f, buckets=by_bucket, bios=bios
    )
    os.makedirs("public", exist_ok=True)
    with open("public/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Done. Items={len(feed_f)+len(blog_f)} → public/index.html")

if __name__ == "__main__":
    main()
