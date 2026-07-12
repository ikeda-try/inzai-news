#!/usr/bin/env python3
"""
印西ニュース - HTML生成スクリプト（Coworkスケジュールタスク用）

使い方:
  python build_html.py articles_final.json [repo_dir]

引数:
  articles_final.json - Claudeが精査・カテゴリ分類した記事のJSONファイル
  repo_dir            - gitリポジトリのディレクトリ（省略時は script と同じ場所）

articles_final.json のフォーマット:
[
  {
    "title": "記事タイトル",
    "link": "https://...",
    "pub_str": "2026年7月12日",
    "publisher": "千葉日報",
    "category": "話題・その他",
    "desc": "説明文（省略可）"
  },
  ...
]

カテゴリの選択肢:
  話題・その他 / イベント・文化 / 印西市役所 / 教育・子育て /
  開発・街づくり / 行政・市政 / 防災・安全
"""

import json
import html
import sys
import os
import subprocess
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

CATEGORY_ORDER = [
    "話題・その他", "イベント・文化", "印西市役所", "教育・子育て",
    "開発・街づくり", "行政・市政", "防災・安全"
]

CATEGORY_COLORS = {
    "印西市役所":     ("#E8EDF8", "#2C5282", "#1A325A"),
    "開発・街づくり": ("#E1F5EE", "#1D9E75", "#085041"),
    "行政・市政":     ("#E6F1FB", "#378ADD", "#0C447C"),
    "イベント・文化": ("#FAEEDA", "#EF9F27", "#633806"),
    "教育・子育て":   ("#EAF3DE", "#639922", "#27500A"),
    "防災・安全":     ("#FCEBEB", "#E24B4A", "#791F1F"),
    "話題・その他":   ("#DFD9CF", "#7A6E5F", "#3D342A"),
}

CATEGORY_ICONS = {
    "印西市役所":     "🏢",
    "開発・街づくり": "🏗️",
    "行政・市政":     "🏛️",
    "イベント・文化": "🎉",
    "教育・子育て":   "📚",
    "防災・安全":     "🚨",
    "話題・その他":   "📰",
}

CSS = """\
*{box-sizing:border-box;margin:0;padding:0}
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
.cat-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:0 12px 4px;grid-auto-rows:270px}
.cat-section{border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.07);display:flex;flex-direction:column}
.cat-header{display:flex;align-items:center;gap:8px;padding:10px 12px}
.cat-icon{font-size:15px}
.cat-name{font-size:12px;font-weight:700;flex:1}
.cat-count{font-size:11px;font-weight:600}
.news-item{display:flex;flex-direction:column;gap:3px;padding:9px 12px;background:#fff;border-top:1px solid #ededea;transition:background .15s}
.news-item:hover{background:#f9f9f6}
.news-title{font-size:13px;font-weight:500;color:#1a1a18;line-height:1.5}
.news-item:hover .news-title{color:#1D9E75}
.news-date{font-size:10px;color:#aaa}
.cat-items{flex:1;overflow-y:auto;min-height:0}
.cat-items::-webkit-scrollbar{width:4px}
.cat-items::-webkit-scrollbar-track{background:transparent}
.cat-items::-webkit-scrollbar-thumb{background:#d0d0cc;border-radius:2px}
.no-news{padding:20px;color:#888;font-size:14px;background:#fff;margin:12px}
@media(max-width:480px){.cat-grid{grid-template-columns:1fr}}
footer{text-align:center;font-size:11px;color:#aaa;padding:24px 20px 0}
"""

GA_TAG = """\
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-89CXHHR0XZ"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-89CXHHR0XZ');
</script>
"""


def build_html(articles):
    now_str = datetime.now(JST).strftime("%Y年%-m月%-d日 %H:%M")

    from collections import defaultdict
    cat_map = defaultdict(list)
    for item in articles:
        cat = item.get("category", "話題・その他")
        if cat not in CATEGORY_COLORS:
            cat = "話題・その他"
        cat_map[cat].append(item)

    top_item = articles[0] if articles else None

    # トップニュース
    if top_item:
        cat = top_item.get("category", "話題・その他")
        if cat not in CATEGORY_COLORS:
            cat = "話題・その他"
        bg, fg, dark = CATEGORY_COLORS[cat]
        hero_pub = " · " + html.escape(top_item["publisher"]) if top_item.get("publisher") else ""
        top_html = (
            '<div class="hero" style="border-color:' + fg + ';">'
            + '<div class="hero-label" style="background:' + fg + ';color:#fff;">'
            + CATEGORY_ICONS[cat] + " " + html.escape(cat) + "</div>"
            + '<a class="hero-title" href="' + html.escape(top_item["link"]) + '" target="_blank" rel="noopener">'
            + html.escape(top_item["title"]) + "</a>"
            + '<div class="hero-meta">' + html.escape(top_item["pub_str"]) + hero_pub + "</div>"
            + "</div>"
        )
    else:
        top_html = ""

    # カテゴリ別セクション（トップ記事を除いた残り）
    remaining = articles[1:] if len(articles) > 1 else []
    cat_map2 = defaultdict(list)
    for item in remaining:
        cat = item.get("category", "話題・その他")
        if cat not in CATEGORY_COLORS:
            cat = "話題・その他"
        cat_map2[cat].append(item)

    grid_items_html = ""
    for cat in CATEGORY_ORDER:
        cat_items = cat_map2.get(cat, [])
        if not cat_items:
            continue
        bg, fg, dark = CATEGORY_COLORS[cat]
        icon = CATEGORY_ICONS[cat]
        rows = ""
        for item in cat_items:
            pub = item.get("publisher", "")
            pub_html = " · " + html.escape(pub) if pub else ""
            rows += (
                '<a class="news-item" href="' + html.escape(item["link"]) + '" target="_blank" rel="noopener">'
                + '<span class="news-title">' + html.escape(item["title"]) + "</span>"
                + '<span class="news-date">' + html.escape(item["pub_str"]) + pub_html + "</span>"
                + "</a>"
            )
        grid_items_html += (
            '<div class="cat-section">'
            + '<div class="cat-header" style="background:' + bg + ';border-left:4px solid ' + fg + ';">'
            + '<span class="cat-icon">' + icon + "</span>"
            + '<span class="cat-name" style="color:' + dark + ';">' + html.escape(cat) + "</span>"
            + '<span class="cat-count" style="color:' + fg + ';">' + str(len(cat_items)) + "件</span>"
            + "</div>"
            + '<div class="cat-items">' + rows + "</div>"
            + "</div>"
        )

    if grid_items_html:
        sections_html = '<div class="cat-grid">' + grid_items_html + "</div>"
    else:
        sections_html = '<p class="no-news">現在ニュースを取得できませんでした。しばらくお待ちください。</p>'

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
    """index.html をコミットしてpush"""
    # トークン読み込み
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
        ["git", "-C", repo_dir, "push", "--force"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # "nothing to commit" は正常
            if "nothing to commit" in result.stdout + result.stderr:
                print("変更なし。pushをスキップします。")
                return True
            print(f"エラー: {' '.join(cmd)}")
            print(result.stderr)
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

    # JSONを読み込む
    with open(json_path, encoding="utf-8") as f:
        articles = json.load(f)

    print(f"{len(articles)}件の記事でHTMLを生成中...")
    html_content = build_html(articles)

    out_path = os.path.join(repo_dir, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"index.html を生成しました → {out_path}")

    # git push
    git_push(repo_dir, token_path)


if __name__ == "__main__":
    main()
