#!/usr/bin/env python3
"""
印西ニュース - RSS収集＋Webスクレイピングスクリプト（GitHub Actions用）
RSSフィードの取得とWebスクレイピングを行い、articles_raw.json に保存する。
HTML生成はCoworkスケジュールタスク（Claude AI）が担当する。
"""

import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import html
import re
import json
import os
from urllib.parse import urlparse

JST = timezone(timedelta(hours=9))

def resolve_google_news_url(url, timeout=5):
    """Google NewsのエンコードURLをリダイレクト先の実際のURLに変換"""
    if 'news.google.com/rss/articles/' not in url:
        return url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.url
    except Exception:
        return url


def resolve_all_google_news(items, max_workers=10):
    """Google News URLを並列で実際のURLに解決"""
    indices = [i for i, it in enumerate(items) if 'news.google.com/rss/articles/' in it.get('link', '')]
    if not indices:
        return items
    print(f"Google News URL を解決中... ({len(indices)}件)")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_map = {ex.submit(resolve_google_news_url, items[i]['link']): i for i in indices}
        for future in as_completed(future_map):
            i = future_map[future]
            try:
                items[i]['link'] = future.result()
            except Exception:
                pass
    return items


RSS_SOURCES = [
    {
        "url": "https://www.city.inzai.lg.jp/rss/rss_new.xml",
        "label": "印西市公式",
        "publisher": "印西市",
        "source": "市役所公式",
    },
    {
        "url": "https://news.google.com/rss/search?q=%E5%8D%B0%E8%A5%BF%E5%B8%82&hl=ja&gl=JP&ceid=JP:ja",
        "label": "印西市",
        "publisher": None,
    },
    {
        "url": "https://news.google.com/rss/search?q=%E5%8D%B0%E8%A5%BF+%E5%8D%83%E8%91%89&hl=ja&gl=JP&ceid=JP:ja",
        "label": "印西（千葉）",
        "publisher": None,
    },
    {
        "url": "https://news.google.com/rss/search?q=%E5%8D%B0%E8%A5%BF%E5%B8%82+%E3%81%8A%E7%9F%A5%E3%82%89%E3%81%9B&hl=ja&gl=JP&ceid=JP:ja",
        "label": "印西市お知らせ",
        "publisher": None,
    },
    {
        "url": "https://news.google.com/rss/search?q=%E5%8D%B0%E8%A5%BF+%E3%82%B0%E3%83%AB%E3%83%A1+%E9%A3%B2%E9%A3%9F%E5%BA%97&hl=ja&gl=JP&ceid=JP:ja",
        "label": "印西グルメ",
        "publisher": None,
    },
    {
        "url": "https://news.google.com/rss/search?q=%E5%8D%B0%E8%A5%BF+%E3%82%A4%E3%83%99%E3%83%B3%E3%83%88+%E3%81%BE%E3%81%A4%E3%82%8A&hl=ja&gl=JP&ceid=JP:ja",
        "label": "印西イベント",
        "publisher": None,
    },
    {
        "url": "https://news.google.com/rss/search?q=%E5%8D%B0%E8%A5%BF+%E9%96%8B%E5%BA%97+%E6%96%B0%E3%82%AA%E3%83%BC%E3%83%97%E3%83%B3&hl=ja&gl=JP&ceid=JP:ja",
        "label": "印西新店舗",
        "publisher": None,
    },
    {
        "url": "https://prtimes.jp/companyrdf.php?company_id=180020",
        "label": "印西市PR TIMES(公式)",
        "publisher": "PR TIMES",
        "source": "市役所公式",
    },
]


def _local_tag(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def fetch_rss(source):
    url = source["url"]
    fixed_publisher = source.get("publisher")
    src_label = source.get("source", "")
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        item_elements = [el for el in root.iter() if _local_tag(el.tag) == "item"]

        for item in item_elements:
            title = link = desc = pub_raw = ""
            for child in item:
                name = _local_tag(child.tag)
                if name == "title":
                    title = child.text or ""
                elif name == "link":
                    link = child.text or ""
                elif name == "description":
                    desc = child.text or ""
                elif name in ("pubDate", "date"):
                    pub_raw = child.text or ""

            title = html.unescape(title)
            desc = html.unescape(re.sub(r"<[^>]+>", "", desc))

            if fixed_publisher is None:
                publisher_match = re.search(r"\s*-\s*([^-]+)$", title)
                publisher = publisher_match.group(1).strip() if publisher_match else ""
                title = re.sub(r"\s*-\s*[^-]+$", "", title).strip()
            else:
                publisher = fixed_publisher

            pub_dt = None
            try:
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(pub_raw).astimezone(JST)
            except Exception:
                try:
                    pub_dt = datetime.fromisoformat(pub_raw).astimezone(JST)
                except Exception:
                    pub_dt = datetime.now(JST)

            if title and link:
                items.append({
                    "title": title,
                    "link": link,
                    "desc": desc[:200] if len(desc) > 200 else desc,
                    "pub_iso": pub_dt.isoformat(),
                    "pub_str": pub_dt.strftime("%Y年%-m月%-d日"),
                    "publisher": publisher,
                    "source": src_label,
                    "source_label": source["label"],
                })
    except Exception as e:
        print(f"RSS取得エラー ({url}): {e}")
    return items


def scrape_site(source):
    """
    scrape_sources.json の1エントリを取得・パースして記事リストを返す。
    日付形式: YYYY/MM/DD がリンクテキストの先頭にある形式に対応。
    """
    url = source["url"]
    name = source["name"]
    publisher = source.get("publisher", name)
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")

        pattern = re.compile(
            r'<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', re.IGNORECASE
        )
        seen_links = set()
        parsed_base = urlparse(url)

        for m in pattern.finditer(raw):
            href = m.group(1)
            text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            text = html.unescape(text)

            date_m = re.match(r"(\d{4})/(\d{2})/(\d{2})", text)
            if not date_m:
                continue

            year = int(date_m.group(1))
            mon = int(date_m.group(2))
            day = int(date_m.group(3))
            title = text[date_m.end():].strip()
            # カテゴリ前置詞を除去
            title = re.sub(r"^(お知らせ|イベント|ショップ|その他)\s*", "", title).strip()
            if not title:
                continue

            # 絶対URLに変換
            if href.startswith("/"):
                href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
            elif not href.startswith("http"):
                continue

            if href in seen_links:
                continue
            seen_links.add(href)

            pub_str = f"{year}年{mon}月{day}日"
            pub_dt = datetime(year, mon, day, tzinfo=JST)
            items.append({
                "title": title,
                "link": href,
                "pub_str": pub_str,
                "pub_iso": pub_dt.isoformat(),
                "publisher": publisher,
                "category": name,
            })

        print(f"  スクレイピング完了: {name} → {len(items)}件")
    except Exception as e:
        print(f"  スクレイピングエラー ({name}): {e}")
    return items


def main():
    all_items = []
    seen_titles = set()

    for source in RSS_SOURCES:
        print(f"取得中: {source['label']}")
        items = fetch_rss(source)
        for item in items:
            key = item["title"][:30]
            if key not in seen_titles:
                seen_titles.add(key)
                all_items.append(item)

    all_items = resolve_all_google_news(all_items)
    all_items.sort(key=lambda x: x["pub_iso"], reverse=True)

    # scrape_sources.json を読んで各サイトを取得
    scraped_items = []
    scrape_path = os.path.join(os.path.dirname(__file__), "scrape_sources.json")
    if os.path.exists(scrape_path):
        with open(scrape_path, encoding="utf-8") as f:
            scrape_sources = json.load(f)
        for src in scrape_sources:
            name = src["name"]
            if src.get("rss_feed_url"):
                # RSS フィードがあればそちらを優先
                print(f"RSS取得中（scraped）: {name}")
                rss_src = {
                    "url": src["rss_feed_url"],
                    "label": name,
                    "publisher": src.get("publisher", name),
                    "source": "",
                }
                items = fetch_rss(rss_src)
                # category をサイト名に上書き
                for item in items:
                    item["category"] = name
                scraped_items.extend(items)
                print(f"  → {len(items)}件")

            else:
                print(f"スクレイピング中: {name}")
                items = scrape_site(src)
                scraped_items.extend(items)

    output = {
        "fetched_at": datetime.now(JST).isoformat(),
        "count": len(all_items[:200]),
        "articles": all_items[:200],
        "scraped": scraped_items,
    }

    out_path = os.path.join(os.path.dirname(__file__), "articles_raw.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nRSS {len(all_items[:200])}件 + スクレイピング {len(scraped_items)}件 → articles_raw.json に保存しました")


if __name__ == "__main__":
    main()
