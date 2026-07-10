#!/usr/bin/env python3
"""
印西ニュース - 自動ニュースサイト生成スクリプト
Google News RSSから印西関連ニュースを取得し、index.htmlを生成します。
"""

import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
import html
import re
import os

JST = timezone(timedelta(hours=9))

RSS_SOURCES = [
    {
        "url": "https://news.google.com/rss/search?q=%E5%8D%B0%E8%A5%BF%E5%B8%82&hl=ja&gl=JP&ceid=JP:ja",
        "label": "Google News",
    },
    {
        "url": "https://news.google.com/rss/search?q=%E5%8D%B0%E8%A5%BF+%E5%8D%83%E8%91%89&hl=ja&gl=JP&ceid=JP:ja",
        "label": "Google News (千葉)",
    },
]

CATEGORY_KEYWORDS = {
    "開発・街づくり": ["開発", "建設", "マンション", "住宅", "ニュータウン", "商業", "物流", "工場", "整備", "道路"],
    "行政・市政": ["市役所", "市議会", "行政", "条例", "予算", "選挙", "市長", "補助", "申請", "税"],
    "イベント・文化": ["イベント", "まつり", "祭り", "コンサート", "展示", "文化", "スポーツ", "大会", "催し"],
    "教育・子育て": ["学校", "保育", "幼稚園", "子育て", "教育", "入学", "PTА"],
    "防災・安全": ["防災", "避難", "台風", "地震", "洪水", "火災", "事故", "注意", "警戒"],
    "話題・その他": [],
}

def get_category(title, summary):
    text = title + " " + summary
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(k in text for k in keywords):
            return cat
    return "話題・その他"

CATEGORY_COLORS = {
    "開発・街づくり": ("#E1F5EE", "#0F6E56", "#085041"),
    "行政・市政":     ("#E6F1FB", "#185FA5", "#0C447C"),
    "イベント・文化": ("#FAEEDA", "#854F0B", "#633806"),
    "教育・子育て":   ("#EAF3DE", "#3B6D11", "#27500A"),
    "防災・安全":     ("#FCEBEB", "#A32D2D", "#791F1F"),
    "話題・その他":   ("#F1EFE8", "#5F5E5A", "#444441"),
}

def fetch_rss(url):
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        channel = root.find("channel")
        if channel is None:
            return items
        for item in channel.findall("item"):
            title_el = item.find("title")
            link_el  = item.find("link")
            desc_el  = item.find("description")
            pub_el   = item.find("pubDate")

            title   = html.unescape(title_el.text or "") if title_el is not None else ""
            link    = link_el.text or "" if link_el is not None else ""
            desc    = html.unescape(re.sub(r"<[^>]+>", "", desc_el.text or "")) if desc_el is not None else ""
            pub_raw = pub_el.text or "" if pub_el is not None else ""

            # Google Newsのタイトルから「 - メディア名」を除去
            title = re.sub(r"\s*-\s*[^-]+$", "", title).strip()

            try:
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(pub_raw).astimezone(JST)
            except Exception:
                pub_dt = datetime.now(JST)

            if title:
                items.append({
                    "title": title,
                    "link": link,
                    "desc": desc[:120] + "…" if len(desc) > 120 else desc,
                    "pub_dt": pub_dt,
                    "pub_str": pub_dt.strftime("%Y年%-m月%-d日"),
                })
    except Exception as e:
        print(f"RSS取得エラー ({url}): {e}")
    return items


def fetch_all_news():
    all_items = []
    seen_titles = set()
    for source in RSS_SOURCES:
        items = fetch_rss(source["url"])
        for item in items:
            key = item["title"][:30]
            if key not in seen_titles:
                seen_titles.add(key)
                all_items.append(item)
    all_items.sort(key=lambda x: x["pub_dt"], reverse=True)
    return all_items[:30]


def build_html(items):
    now_str = datetime.now(JST).strftime("%Y年%-m月%-d日 %H:%M")
    top_item = items[0] if items else None
    rest = items[1:]

    # トップニュース
    if top_item:
        cat = get_category(top_item["title"], top_item["desc"])
        bg, fg, dark = CATEGORY_COLORS[cat]
        top_html = f"""
    <div class="hero">
      <div class="hero-label">{html.escape(cat)}</div>
      <a class="hero-title" href="{html.escape(top_item['link'])}" target="_blank" rel="noopener">
        {html.escape(top_item['title'])}
      </a>
      <div class="hero-meta">{html.escape(top_item['pub_str'])}</div>
    </div>"""
    else:
        top_html = ""

    # ニュース一覧
    news_rows = ""
    for item in rest:
        cat = get_category(item["title"], item["desc"])
        bg, fg, dark = CATEGORY_COLORS[cat]
        news_rows += f"""
      <a class="news-item" href="{html.escape(item['link'])}" target="_blank" rel="noopener">
        <span class="news-cat" style="background:{bg};color:{dark};">{html.escape(cat)}</span>
        <span class="news-body">
          <span class="news-title">{html.escape(item['title'])}</span>
          <span class="news-date">{html.escape(item['pub_str'])}</span>
        </span>
      </a>"""

    if not news_rows:
        news_rows = '<p class="no-news">現在ニュースを取得できませんでした。しばらくお待ちください。</p>'

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>印西ニュース - 千葉県印西市のニュース</title>
<meta name="description" content="千葉県印西市の最新ニュース・話題をお届けします。">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Hiragino Kaku Gothic ProN','Noto Sans JP',sans-serif;background:#f5f5f0;color:#1a1a18;line-height:1.6}}
a{{text-decoration:none;color:inherit}}
.wrap{{max-width:720px;margin:0 auto;padding:0 0 40px}}
header{{background:#fff;border-bottom:1px solid #e0e0d8;padding:14px 20px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:10}}
.logo{{font-size:20px;font-weight:600;color:#1a1a18}}.logo span{{color:#1D9E75}}
.updated{{font-size:11px;color:#888;text-align:right}}
.hero{{background:#fff;margin:0 0 2px;padding:18px 20px;border-bottom:3px solid #1D9E75}}
.hero-label{{font-size:11px;font-weight:600;color:#1D9E75;margin-bottom:6px;text-transform:uppercase;letter-spacing:.05em}}
.hero-title{{font-size:19px;font-weight:600;color:#1a1a18;line-height:1.45;display:block;margin-bottom:6px}}
.hero-title:hover{{color:#1D9E75}}
.hero-meta{{font-size:12px;color:#888}}
.section-label{{font-size:11px;font-weight:600;color:#888;padding:14px 20px 8px;letter-spacing:.05em;text-transform:uppercase;background:#f5f5f0}}
.news-item{{display:flex;gap:10px;align-items:flex-start;padding:12px 20px;background:#fff;border-bottom:1px solid #ededea;transition:background .15s}}
.news-item:hover{{background:#f9f9f6}}
.news-cat{{font-size:10px;font-weight:600;padding:2px 8px;border-radius:10px;white-space:nowrap;flex-shrink:0;margin-top:3px}}
.news-body{{display:flex;flex-direction:column;gap:3px}}
.news-title{{font-size:14px;font-weight:500;color:#1a1a18;line-height:1.5}}
.news-item:hover .news-title{{color:#1D9E75}}
.news-date{{font-size:11px;color:#aaa}}
.no-news{{padding:20px;color:#888;font-size:14px;background:#fff}}
footer{{text-align:center;font-size:11px;color:#aaa;padding:24px 20px 0}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">印西<span>ニュース</span></div>
    <div class="updated">最終更新<br>{now_str}</div>
  </header>
  {top_html}
  <div class="section-label">最新ニュース</div>
  <div class="news-list">
    {news_rows}
  </div>
  <footer>
    © 印西ニュース — Google Newsより自動収集。記事の著作権は各メディアに帰属します。
  </footer>
</div>
</body>
</html>"""


def main():
    print("ニュースを取得中...")
    items = fetch_all_news()
    print(f"{len(items)}件取得しました")

    html_content = build_html(items)

    out_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"index.html を生成しました → {out_path}")


if __name__ == "__main__":
    main()
