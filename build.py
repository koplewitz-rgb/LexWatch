import feedparser, yaml, os, datetime

def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def fetch_feed(url):
    try:
        return feedparser.parse(url).entries
    except Exception as e:
        print("Error fetching", url, e)
        return []

def main():
    cfg = load_config()
    keywords = [k.lower() for k in cfg["keywords"]]
    blogs = cfg["blogs"]
    names = [n.lower() for n in cfg["names"]]

    all_items = []
    for blog in blogs:
        items = fetch_feed(blog)
        for it in items:
            title = it.get("title", "").lower()
            summary = it.get("summary", "").lower()
            link = it.get("link", "")
            text = title + " " + summary

            if "israel" in text and any(k in text for k in keywords):
                who = [n for n in names if n in text]
                all_items.append({
                    "title": it.get("title"),
                    "link": link,
                    "summary": it.get("summary", ""),
                    "who": who
                })

    # write HTML report
    os.makedirs("site", exist_ok=True)
    out = os.path.join("site", "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write("<html><head><title>LexWatch Report</title></head><body>")
        f.write(f"<h1>LexWatch Report - {datetime.date.today()}</h1>")
        if not all_items:
            f.write("<p>No matching items found today.</p>")
        else:
            for it in all_items:
                f.write(f"<h3><a href='{it['link']}'>{it['title']}</a></h3>")
                f.write(f"<p>{it['summary']}</p>")
                if it['who']:
                    f.write(f"<p><b>Mentions:</b> {', '.join(it['who'])}</p>")
        f.write("</body></html>")

if __name__ == "__main__":
    main()
