#!/usr/bin/env python3
"""
印西ニュース - HTML生成スクリプト（Coworkスケジュールタスク用）
"""

import json, html, sys, os, re, subprocess
from datetime import datetime, timezone, timedelta, date
from collections import defaultdict

JST = timezone(timedelta(hours=9))
MAX_ITEMS_PER_CAT = 10
CATEGORY_MAX_ITEMS = {
    "市政・行政": 6,
}
SCRAPED_MAX_ITEMS = 5
SCRAPED_MAX_DAYS = 90

CATEGORY_ORDER = ["話題・その他", "イベント・文化", "市政・行政", "開発・暮らし"]

CATEGORY_COLORS = {
    "話題・その他":   ("#DFD9CF", "#7A6E5F", "#3D342A"),
    "イベント・文化": ("#F0EAFA", "#9B59B6", "#6C3483"),
    "市政・行政":     ("#E8EDF8", "#2C5282", "#1A325A"),
    "開発・暮らし":   ("#E1F5EE", "#1D9E75", "#085041"),
}

CATEGORY_ICONS = {
    "話題・その他":   "📰",
    "イベント・文化": "🎉",
    "市政・行政":     "🏢",
    "開発・暮らし":   "🌱",
}

SCRAPED_COLOR = ("#EDE8F8", "#6B4FA7", "#3A1F6E")
SCRAPED_ICON = "📍"

CSS = """*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Hiragino Kaku Gothic ProN','Noto Sans JP',sans-serif;background:#f0f0ec;color:#1a1a18;line-height:1.6}
a{text-decoration:none;color:inherit}
.wrap{max-width:720px;margin:0 auto;padding:0 0 48px}
header{background:#fff;border-bottom:1px solid #e0e0d8;padding:14px 20px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:10}
.logo{font-size:20px;font-weight:600;color:#1a1a18}.logo span{color:#1D9E75}
.updated{font-size:11px;color:#888;text-align:right}
.hero{background:#fff;margin:0 0 16px;padding:18px 20px;border-bottom:3px solid #1D9E75}
.hero-label{display:inline-block;font-size:11px;font-weight:700;margin-bottom:8px;letter-spacing:.03em;padding:3px 8px;border-radius:4px}
.hero-title{font-size:19px;font-weight:600;color:#1a1a18;line-height:1.45;display:block;margin-bottom:6px}
.hero-title:hover{color:#1D9E75}
.hero-meta{font-size:12px;color:#888}
.today-badge{display:inline-block;font-size:10px;font-weight:700;background:#e74c3c;color:#fff;padding:1px 6px;border-radius:3px;margin-left:6px;vertical-align:middle}
.cat-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:0 12px 4px;grid-auto-rows:270px}
.scraped-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px 12px 4px;grid-auto-rows:200px}
.cat-section{border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.07);display:flex;flex-direction:column}
.cat-header{display:flex;align-items:center;gap:8px;padding:10px 12px}
.cat-icon{font-size:15px}
.cat-name{font-size:12px;font-weight:700;flex:1}
.cat-count{font-size:11px;font-weight:600}
.news-item{display:flex;flex-direction:column;gap:3px;padding:9px 12px;background:#fff;border-top:1px solid #ededea;transition:background .15s}
.news-item:hover{background:#f9f9f6}
.news-item.today{background:#fffbe8}
.news-item.today:hover{background:#fff5cc}
.news-item.recent{background:#fffbe8}
.news-item.recent:hover{background:#fff5cc}
.news-title{font-size:13px;font-weight:500;color:#1a1a18;line-height:1.5}
.news-item:hover .news-title{color:#1D9E75}
.news-date{font-size:10px;color:#aaa}
.cat-items{flex:1;overflow-y:auto;min-height:0}
.cat-items::-webkit-scrollbar{width:4px}
.cat-items::-webkit-scrollbar-track{background:transparent}
.cat-items::-webkit-scrollbar-thumb{background:#d0d0cc;border-radius:2px}
.no-news{padding:20px;color:#888;font-size:14px;background:#fff;margin:12px}
@media(max-width:480px){.cat-grid,.scraped-grid{grid-template-columns:1fr}}
footer{text-align:center;font-size:11px;color:#aaa;padding:24px 20px 0}
"""

GA_TAG = """<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-89CXHHR0XZ"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-89CXHHR0XZ');
</script>
"""


def parse_pub_date(pub_str):
    m = re.match(r'(\d{4})年(\d+)月(\d+)日', pub_str or "")
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def get_date_class(pub_str):
    today = datetime.now(JST).date()
    d = parse_pub_date(pub_str)
    if d is None:
        return ""
    delta = (today - d).days
    if delta == 0:
        return "today"
    elif delta <= 3:
        return "recent"
    return ""


def render_item(item):
    pub = item.get("publisher", "")
    pub_html = " · " + html.escape(pub) if pub else ""
    date_cls = get_date_class(item.get("pub_str", ""))
    cls_suffix = " " + date_cls if date_cls else ""
    return (
        '<a class="news-item' + cls_suffix + '" href="' + html.escape(item["link"]) + '" target="_blank" rel="noopener">'
        + '<span class="news-title">' + html.escape(item["title"]) + "</span>"
        + '<span class="news-date">' + html.escape(item.get("pub_str", "")) + pub_html + "</span>"
        + "</a>"
    )


def build_html(articles):
    now_str = datetime.now(JST).strftime("%Y年%-m月%-d日 %H:%M")
    today = datetime.now(JST).date()
    cutoff = today - timedelta(days=SCRAPED_MAX_DAYS)

    main_arts = [a for a in articles if a.get("category") in CATEGORY_ORDER]
    scraped_arts = [a for a in articles if a.get("category") not in CATEGORY_ORDER]

    top_item = main_arts[0] if main_arts else None

    if top_item:
        cat = top_item.get("category", "話題・その他")
        bg, fg, dark = CATEGORY_COLORS.get(cat, CATEGORY_COLORS["話題・その他"])
        pub_h = " · " + html.escape(top_item["publisher"]) if top_item.get("publisher") else ""
        badge = '<span class="today-badge">今日</span>' if get_date_class(top_item.get("pub_str", "")) == "today" else ""
        top_html = (
            '<div class="hero" style="border-color:' + fg + ';">'
            + '<div class="hero-label" style="background:' + fg + ';color:#fff;">'
            + CATEGORY_ICONS.get(cat, "📰") + " " + html.escape(cat) + "</div>"
            + '<a class="hero-title" href="' + html.escape(top_item["link"]) + '" target="_blank" rel="noopener">'
            + html.escape(top_item["title"]) + "</a>"
            + '<div class="hero-meta">' + html.escape(top_item.get("pub_str", "")) + pub_h + badge + "</div>"
            + "</div>"
        )
    else:
        top_html = ""

    cat_map = defaultdict(list)
    for item in main_arts[1:]:
        cat_map[item.get("category", "話題・その他")].append(item)

    grid_html = ""
    for cat in CATEGORY_ORDER:
        cap = CATEGORY_MAX_ITEMS.get(cat, MAX_ITEMS_PER_CAT)
        items = cat_map.get(cat, [])[:cap]
        if not items:
            continue
        bg, fg, dark = CATEGORY_COLORS[cat]
        rows = "".join(render_item(i) for i in items)
        grid_html += (
            '<div class="cat-section">'
            + '<div class="cat-header" style="background:' + bg + ';border-left:4px solid ' + fg + ';">'
            + '<span class="cat-icon">' + CATEGORY_ICONS[cat] + "</span>"
            + '<span class="cat-name" style="color:' + dark + ';">' + html.escape(cat) + "</span>"
            + '<span class="cat-count" style="color:' + fg + ';">' + str(len(items)) + "件</span>"
            + "</div>"
            + '<div class="cat-items">' + rows + "</div>"
            + "</div>"
        )
    sections_html = '<div class="cat-grid">' + grid_html + "</div>" if grid_html else '<p class="no-news">現在ニュースを取得できませんでした。</p>'

    scraped_map = defaultdict(list)
    for item in scraped_arts:
        scraped_map[item.get("category", "地域情報")].append(item)

    scraped_html = ""
    for site, items in scraped_map.items():
        filtered = [i for i in items if (parse_pub_date(i.get("pub_str", "")) or cutoff) >= cutoff][:SCRAPED_MAX_ITEMS]
        if not filtered:
            continue
        bg, fg, dark = SCRAPED_COLOR
        rows = "".join(render_item(i) for i in filtered)
        scraped_html += (
            '<div class="cat-section">'
            + '<div class="cat-header" style="background:' + bg + ';border-left:4px solid ' + fg + ';">'
            + '<span class="cat-icon">' + SCRAPED_ICON + "</span>"
            + '<span class="cat-name" style="color:' + dark + ';">' + html.escape(site) + "</span>"
            + '<span class="cat-count" style="color:' + fg + ';">' + str(len(filtered)) + "件</span>"
            + "</div>"
            + '<div class="cat-items">' + rows + "</div>"
            + "</div>"
        )
    if scraped_html:
        sections_html += '<div class="scraped-grid">' + scraped_html + "</div>"

    parts = [
        "<!DOCTYPE html>\n<html lang=\"ja\">\n<head>\n",
        "<meta charset=\"UTF-8\">\n",
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n",
        "<title>印西ニュース - 千葉県印西市のニュース</title>\n",
        "<meta name=\"description\" content=\"千葉県印西市の最新ニュース・話題をお届けします。\">\n",
        "<link rel=\"icon\" type=\"image/png\" href=\"favicon.png\">\n",
        GA_TAG,
        "<style>\n", CSS, "</style>\n",
        "</head>\n<body>\n",
        "<div class=\"wrap\">\n",
        "  <header>\n",
        "    <div class=\"logo\">印西<span>ニュース</span></div>\n",
        "    <div class=\"updated\">最終更新<br>" + now_str + "</div>\n",
        "  </header>\n",
        "  " + top_html + "\n",
        "  " + sections_html + "\n",
        "  <footer>\n",
        "    &copy; 印西ニュース &mdash; Google News・印西市公式サイト・地域情報より自動収集。記事の著作権は各メディアに帰属します。\n",
        "  </footer>\n",
        "</div>\n</body>\n</html>",
    ]
    return "".join(parts)


def git_push(repo_dir, token_path):
    token = ""
    if os.path.exists(token_path):
        with open(token_path) as f:
            token = f.read().strip()
    if not token:
        print("警告: トークンが見つかりません。git pushをスキップします。")
        return False
    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    cmds = [
        ["git", "-C", repo_dir, "config", "user.name", "cowork-bot"],
        ["git", "-C", repo_dir, "config", "user.email", "cowork-bot@users.noreply.github.com"],
        ["git", "-C", repo_dir, "add", "index.html"],
        ["git", "-C", repo_dir, "commit", "-m", f"AI精査更新: {now_str}"],
        ["git", "-C", repo_dir, "push"],
    ]
    for cmd in cmds:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            if "nothing to commit" in r.stdout + r.stderr:
                print("変更なし。pushをスキップします。")
                return True
            print(f"エラー: {' '.join(cmd)}\n{r.stderr}")
            return False
    print("git push 完了")
    return True


def main():
    if len(sys.argv) < 2:
        print("使い方: python build_html.py articles_final.json [repo_dir]")
        sys.exit(1)
    json_path = sys.argv[1]
    repo_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(__file__))
    token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".gh_token")

    with open(json_path, encoding="utf-8") as f:
        articles = json.load(f)

    print(f"{len(articles)}件の記事でHTMLを生成中...")
    html_content = build_html(articles)

    out_path = os.path.join(repo_dir, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"index.html を生成しました → {out_path}")
    git_push(repo_dir, token_path)


if __name__ == "__main__":
    main()
