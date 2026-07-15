#!/usr/bin/env python3
"""
印西ニュース - HTML生成スクリプト（Coworkスケジュールタスク用）
"""

import json, html, sys, os, re, subprocess
from datetime import datetime, timezone, timedelta, date
from collections import defaultdict

JST = timezone(timedelta(hours=9))
MAX_ITEMS_PER_CAT = 20
CATEGORY_MAX_ITEMS = {}
SCRAPED_MAX_ITEMS = 20
SCRAPED_MAX_DAYS = 180
CATEGORY_CUTOFF_DAYS = {"開店・閉店": 180, "イオンモール千葉ニュータウン": 180, "鎌ヶ谷・白井": 90}
DEFAULT_CUTOFF_DAYS = 90

CATEGORY_ORDER = ["話題・その他", "イベント・文化", "市政・行政", "開発・暮らし", "開店・閉店", "鎌ヶ谷・白井", "イオンモール千葉ニュータウン"]

CATEGORY_COLORS = {
    "話題・その他":   ("#F3F4F6", "#6B7280", "#374151"),
    "イベント・文化": ("#F3E8FF", "#9333EA", "#6B21A8"),
    "市政・行政":     ("#E8F1FF", "#2563EB", "#1E3A8A"),
    "開発・暮らし":   ("#ECFDF5", "#10B981", "#065F46"),
    "開店・閉店":     ("#FEF2F2", "#EF4444", "#991B1B"),
    "鎌ヶ谷・白井":   ("#FFF7ED", "#F97316", "#9A3412"),
    "イオンモール千葉ニュータウン": ("#ECFEFF", "#06B6D4", "#155E75"),
}

CATEGORY_ICONS = {
    "話題・その他":   "📰",
    "イベント・文化": "🎉",
    "市政・行政":     "🏛",
    "開発・暮らし":   "🌱",
    "開店・閉店":     "🏪",
    "鎌ヶ谷・白井":   "🗺",
    "イオンモール千葉ニュータウン": "🛍",
}

SCRAPED_COLOR = ("#EDE8F8", "#6B4FA7", "#3A1F6E")
SCRAPED_ICON = "📍"

# --- 出典元の正規化 ---
PUBLISHER_ALIASES = {
    "印西市": "印西市役所",
}
PUBLISHER_URL_FALLBACKS = [
    ("kamagaya-shiroi-inzai.goguynet.jp", "鎌ヶ谷白井インザイ.jp"),
    ("goguynet.jp",                        "goguynet"),
]

def normalize_publisher(pub, link=""):
    """publisherの表記ゆれを正規化し、空の場合はURLからフォールバック"""
    if pub in PUBLISHER_ALIASES:
        return PUBLISHER_ALIASES[pub]
    if not pub:
        for domain, name in PUBLISHER_URL_FALLBACKS:
            if domain in (link or ""):
                return name
    return pub

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
@media(max-width:480px){.cat-grid,.scraped-grid{grid-template-columns:1fr;gap:20px}}
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


def kaiten_label(item):
    """開店・閉店カテゴリで【日付 開店/閉店】がない場合に自動補完する"""
    if item.get("category") != "開店・閉店":
        return item.get("title", "")
    title = item.get("title", "")
    if title.startswith("【"):
        return title
    kind = "閉店" if "閉店" in title else "開店"
    return f"【{kind}日不明】{title}"


def render_item(item):
    pub = normalize_publisher(item.get("publisher", ""), item.get("link", ""))
    pub_html = " · " + html.escape(pub) if pub else ""
    d = parse_pub_date(item.get("pub_str", ""))
    data_pub = (' data-pub="' + d.isoformat() + '"') if d else ""
    title = kaiten_label(item)
    return (
        '<a class="news-item"' + data_pub + ' href="' + html.escape(item["link"]) + '" target="_blank" rel="noopener">'
        + '<span class="news-title">' + html.escape(title) + "</span>"
        + '<span class="news-date">' + html.escape(item.get("pub_str", "")) + pub_html + '<span class="today-badge" style="display:none">今日</span>' + "</span>"
        + "</a>"
    )


def build_html(articles):
    now_str = datetime.now(JST).strftime("%Y年%-m月%-d日 %H:%M")
    today = datetime.now(JST).date()
    cutoff = today - timedelta(days=SCRAPED_MAX_DAYS)

    # 鎌ヶ谷・白井の開店・閉店記事は「開店・閉店」カテゴリに振り替え
    KAITEN_KEYWORDS = ["開店", "閉店", "オープン", "クローズ", "NEW OPEN", "new open"]
    for a in articles:
        if a.get("category") == "鎌ヶ谷・白井":
            title = a.get("title", "")
            if any(kw in title for kw in KAITEN_KEYWORDS):
                a["category"] = "開店・閉店"

    main_arts_all = [a for a in articles if a.get("category") in CATEGORY_ORDER]
    scraped_arts = [a for a in articles if a.get("category") not in CATEGORY_ORDER]
    def date_ok(item):
        d = parse_pub_date(item.get("pub_str", ""))
        if not d: return True
        days = CATEGORY_CUTOFF_DAYS.get(item.get("category", ""), DEFAULT_CUTOFF_DAYS)
        return d >= today - timedelta(days=days)
    main_arts = [a for a in main_arts_all if date_ok(a)]

    top_item = main_arts[0] if main_arts else None

    if top_item:
        cat = top_item.get("category", "話題・その他")
        bg, fg, dark = CATEGORY_COLORS.get(cat, CATEGORY_COLORS["話題・その他"])
        top_pub = normalize_publisher(top_item.get("publisher", ""), top_item.get("link", ""))
        pub_h = " · " + html.escape(top_pub) if top_pub else ""
        hero_d = parse_pub_date(top_item.get("pub_str", ""))
        hero_pub_attr = (' data-pub="' + hero_d.isoformat() + '"') if hero_d else ""
        top_html = (
            '<div class="hero" style="border-color:' + fg + ';">'
            + '<div class="hero-label" style="background:' + fg + ';color:#fff;">'
            + CATEGORY_ICONS.get(cat, "📰") + " " + html.escape(cat) + "</div>"
            + '<a class="hero-title" href="' + html.escape(top_item["link"]) + '" target="_blank" rel="noopener">'
            + html.escape(top_item["title"]) + "</a>"
            + '<div class="hero-meta"' + hero_pub_attr + '>' + html.escape(top_item.get("pub_str", "")) + pub_h
            + '<span class="today-badge" id="hero-today-badge" style="display:none">今日</span></div>'
            + "</div>"
        )
    else:
        top_html = ""

    cat_map = defaultdict(list)
    for item in main_arts[1:]:
        cat_map[item.get("category", "話題・その他")].append(item)

    active_cats = [
        (cat, cat_map.get(cat, [])[:CATEGORY_MAX_ITEMS.get(cat, MAX_ITEMS_PER_CAT)])
        for cat in CATEGORY_ORDER
        if cat_map.get(cat)
    ]
    grid_html = ""
    for idx, (cat, items) in enumerate(active_cats):
        bg, fg, dark = CATEGORY_COLORS[cat]
        rows = "".join(render_item(i) for i in items)
        grid_html += (
            '<div class="cat-section">'
            + '<div class="cat-header" style="background:' + bg + ';border-left:4px solid ' + fg + ';">'
            + '<span class="cat-icon">' + CATEGORY_ICONS[cat] + "</span>"
            + '<span class="cat-name" style="color:' + dark + ';"> ' + html.escape(cat) + "</span>"
            + '<span class="cat-count" style="color:' + fg + ';"> ' + str(len(items)) + "件</span>"
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
            + '<span class="cat-name" style="color:' + dark + ';"> ' + html.escape(site) + "</span>"
            + '<span class="cat-count" style="color:' + fg + ';"> ' + str(len(filtered)) + "件</span>"
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
        "</div>\n<script>\n(function(){\n  var now=new Date(new Date().toLocaleString(\"en-US\",{timeZone:\"Asia/Tokyo\"}));\n  var jstToday=now.getFullYear()+\"-\"+String(now.getMonth()+1).padStart(2,\"0\")+\"-\"+String(now.getDate()).padStart(2,\"0\");\n  var jst=new Date(jstToday);\n  document.querySelectorAll(\".news-item[data-pub]\").forEach(function(el){\n    var diff=Math.floor((jst-new Date(el.dataset.pub))/86400000);\n    if(diff>=0&&diff<=3) el.classList.add(\"recent\");if(diff===0){var b=el.querySelector(\".today-badge\");if(b)b.style.display=\"\";}\n  });\n  var hm=document.querySelector(\".hero-meta[data-pub]\");\n  if(hm){\n    var diff=Math.floor((jst-new Date(hm.dataset.pub))/86400000);\n    if(diff===0){var b=document.getElementById(\"hero-today-badge\");if(b)b.style.display=\"\";}\n  }\n})();\n</script>\n</body>\n</html>",
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
