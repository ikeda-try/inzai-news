"""印西ニュース 統合パイプライン

サブコマンド:
  collect        ソース収集。ルールベースで判定できるものは news.json に直接反映し、
                 重複グレーゾーン(70-79%)・カテゴリ未確定の記事は review_queue.json に書き出す。
  apply-review   review_queue.json (decision/category を記入済み) を反映して news.json を確定する。
  build          news.json から index.html を生成する。
  publish        変更を git add/commit/push する。
  store-pending  開店閉店.txt の未処理店舗一覧を表示する(6か月経過店舗は自動削除)。
  store-add      調査済みの開店閉店情報を1件 news.json に登録する。
  store-star     開店閉店.txt の店舗に★(調査不能スキップ)を付与する。

実行方法: python pipeline.py <サブコマンド> [オプション]
"""
import argparse
import calendar
import difflib
import html
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from collections import defaultdict

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)

BASE_DIR = Path(__file__).parent
SOURCES_PATH = BASE_DIR / "sources.json"
NEWS_PATH = BASE_DIR / "news.json"
REVIEW_QUEUE_PATH = BASE_DIR / "review_queue.json"
AI_LOG_PATH = BASE_DIR / "ai_check_log.json"
STORE_LIST_PATH = BASE_DIR / "開店閉店.txt"
INDEX_HTML_PATH = BASE_DIR / "index.html"
TOKEN_PATH = BASE_DIR / ".gh_token"
GITHUB_REPO = "inzai-news/news"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}
TIMEOUT = 15
JST = timezone(timedelta(hours=9))

CATEGORY_ORDER = ["話題・その他", "イベント・文化", "市政・行政", "開発・暮らし", "開店・閉店", "鎌ヶ谷・白井", "イオンモール千葉ニュータウン", "牧の原モア"]
KAITEN_KEYWORDS = ["開店", "閉店", "オープン", "クローズ", "NEW OPEN", "new open"]

REGULAR_RETENTION_MONTHS = 3
STORE_EVENT_RETENTION_MONTHS = 6
STORE_EVENT_TITLE_PATTERN = re.compile(r"^【(\d{4})年(\d{1,2})月(\d{1,2})日\s+(開店|閉店|リニューアル)】")

DUP_AUTO_EXCLUDE_THRESHOLD = 0.8
DUP_REVIEW_THRESHOLD = 0.7
DUP_COMPARE_WINDOW_DAYS = 30

RENEWAL_CATEGORY_LABELS = {"新店": "開店", "閉店": "閉店", "リニューアル": "リニューアル"}

# カテゴリ未確定の記事(主にGoogle News経由)に対する、タイトルからの機械的カテゴリ推定。
# ここで判定できないものだけをAI判断(review_queue)に回し、AIへの負荷を抑える。
CATEGORY_KEYWORD_RULES = [
    ("開店・閉店", ["開店", "閉店", "オープン", "OPEN", "open", "クローズ", "close", "移転", "新規出店", "リニューアルオープン"]),
    ("鎌ヶ谷・白井", ["鎌ケ谷", "鎌ヶ谷", "白井市", "白井駅"]),
    ("イオンモール千葉ニュータウン", ["イオンモール", "AEON MALL", "aeonmall", "チバニュータウン", "千葉ニュータウン中央"]),
    ("市政・行政", ["市議会", "市役所", "市政", "市長", "条例", "予算案", "補正予算", "選挙", "行政", "助成金", "補助金", "住民票", "議案"]),
    ("イベント・文化", ["まつり", "祭り", "フェス", "フェスタ", "展示会", "展覧会", "コンサート", "ワークショップ", "講座", "教室", "花火", "マルシェ", "イベント"]),
    ("開発・暮らし", ["データセンター", "再開発", "宅地", "分譲", "駅前", "都市計画", "道路", "子育て", "保育", "ごみ", "防災", "交通"]),
]


def guess_category_from_title(title: str):
    for category, keywords in CATEGORY_KEYWORD_RULES:
        if any(kw in title for kw in keywords):
            return category
    return None


# Google Newsのキーワード検索は関連度が緩く、印西と無関係な記事(他地域のチェーン店開店情報や
# 全く関係ないニュース)が混ざる。タイトルにこれらの地域キーワードが1つも無い記事は対象外として除外する。
LOCAL_AREA_KEYWORDS = [
    "印西", "牧の原", "千葉ニュータウン", "チバニュータウン", "鎌ケ谷", "鎌ヶ谷",
    "白井市", "白井駅", "印旛", "木下駅", "小林駅", "大森駅",
]


def is_locally_relevant(title: str) -> bool:
    return any(kw in title for kw in LOCAL_AREA_KEYWORDS)


# ============================================================
# 共通ユーティリティ
# ============================================================

def to_pub_str(year, month, day) -> str:
    return f"{int(year)}年{int(month)}月{int(day)}日"


def parse_pub_str(pub_str: str):
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", pub_str or "")
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    return date(y, mo, d)


def months_ago(base: date, months: int) -> date:
    month = base.month - months
    year = base.year
    while month <= 0:
        month += 12
        year -= 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def is_store_event_title(title: str) -> bool:
    return bool(STORE_EVENT_TITLE_PATTERN.match(title or ""))


def compute_retention_type(item: dict) -> str:
    return "store_event" if is_store_event_title(item.get("title", "")) else "regular"


def is_expired(item: dict, today=None) -> bool:
    """通常記事は3か月、開店閉店情報(retention_type=store_event)は6か月より古ければTrue。
    通常記事が未来日付になっているのはパースミスとみなして除外対象とする
    (開店閉店情報は開店/閉店の予定日を使うため未来日付でも正常なので対象外)。
    """
    if today is None:
        today = date.today()
    pub_date = parse_pub_str(item.get("pub_str", ""))
    if pub_date is None:
        return False
    is_store_event = item.get("retention_type") == "store_event"
    if not is_store_event and pub_date > today:
        return True
    retention_months = STORE_EVENT_RETENTION_MONTHS if is_store_event else REGULAR_RETENTION_MONTHS
    cutoff = months_ago(today, retention_months)
    return pub_date < cutoff


def title_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a or "", b or "").ratio()


def save_json_atomic(path: Path, data) -> None:
    """一時ファイル経由でアトミックに書き込み、直後に読み直して破損がないか検証する"""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, indent=2)
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
    with path.open(encoding="utf-8") as f:
        json.load(f)


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_news() -> list:
    return load_json(NEWS_PATH, [])


def load_sources() -> dict:
    return load_json(SOURCES_PATH, {"html_scrapers": [], "rss_sources": [], "blocked_publishers": []})


def append_ai_log(entries: list) -> None:
    if not entries:
        return
    log = load_json(AI_LOG_PATH, [])
    log.extend(entries)
    save_json_atomic(AI_LOG_PATH, log)


def load_excluded_links() -> set:
    """過去にルールベース/AI判断で除外(exclude)されたリンクの集合。
    HTMLスクレイパー等、同じ記事が毎回トップページに載り続けるソース向けに、
    一度除外判定した記事を次回collect以降も再度重複判定・AIレビューにかけないための記憶。
    """
    log = load_json(AI_LOG_PATH, [])
    return {e["link"] for e in log if e.get("ai_decision") in ("auto_exclude", "exclude")}


# ============================================================
# HTML直接スクレイピング(RSSが無いサイト)
# ============================================================

def fetch_soup(url: str) -> BeautifulSoup:
    res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    res.raise_for_status()
    return BeautifulSoup(res.text, "html.parser")


def extract_date_groups(text: str):
    normalized = unicodedata.normalize("NFKC", text)
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", normalized)
    if m:
        return m.groups()
    m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", normalized)
    if m:
        return m.groups()
    return None


def scrape_makinohara(cfg, existing_by_link):
    url = cfg["url"]
    soup = fetch_soup(url)
    panel = soup.select_one(".p-home-sec-event-topics-in__panels .js-panel")
    items = []
    if panel is None:
        return items
    for card in panel.select(".p-home-sec-event-topics-in-card"):
        a = card.select_one("a[href]")
        title_tag = card.select_one("h3")
        time_tag = card.select_one("time")
        if not (a and title_tag and time_tag):
            continue
        m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", time_tag.get_text())
        if not m:
            continue
        items.append({
            "title": title_tag.get_text(strip=True),
            "link": a["href"].strip(),
            "pub_str": to_pub_str(*m.groups()),
            "publisher": cfg.get("publisher", cfg["name"]),
            "source": cfg["id"],
            "category": cfg.get("category"),
        })
    return items


def scrape_aeonmall_renewal(cfg, existing_by_link):
    url = cfg["url"]
    soup = fetch_soup(url)
    items = []
    for li in soup.select("li.result-box"):
        a = li.select_one("a[href]")
        title_tag = li.select_one("p.name")
        info_tag = li.select_one("p.info")
        if not (a and title_tag and info_tag):
            continue
        raw_title = title_tag.get_text(strip=True)
        date_groups = extract_date_groups(raw_title) or extract_date_groups(info_tag.get_text())
        if not date_groups:
            continue
        badge_tag = li.select_one(".result-box-badge")
        category_badge = badge_tag.get_text(strip=True) if badge_tag else ""
        label = RENEWAL_CATEGORY_LABELS.get(category_badge, category_badge or "情報")
        tenant_tag = li.select_one("p.tenant")
        tenant_name_node = tenant_tag.find(string=True, recursive=False) if tenant_tag else None
        if tenant_name_node:
            store_name = tenant_name_node.strip()
        else:
            store_name = re.sub(rf"\s*{re.escape(category_badge)}?\s*のお知らせ\s*$", "", raw_title).strip()
        items.append({
            "title": f"【{to_pub_str(*date_groups)} {label}】{store_name}",
            "link": urljoin(url, a["href"].strip()),
            "pub_str": to_pub_str(*date_groups),
            "publisher": cfg.get("publisher", cfg["name"]),
            "source": cfg["id"],
            "category": cfg.get("category"),
        })
    return items


def scrape_aeonmall_event(cfg, existing_by_link):
    url = cfg["url"]
    soup = fetch_soup(url)
    items = []
    skipped = 0
    for li in soup.select("li.result-box"):
        a = li.select_one("a[href]")
        title_tag = li.select_one("p.name")
        if not (a and title_tag):
            continue
        link = urljoin(url, a["href"].strip())
        title = title_tag.get_text(strip=True)
        existing = existing_by_link.get(link)
        if existing and existing.get("title") == title:
            items.append(existing)
            skipped += 1
            continue
        try:
            detail_soup = fetch_soup(link)
        except requests.RequestException as e:
            print(f"[WARN] イベント詳細取得失敗 {link}: {e}", file=sys.stderr)
            continue
        update_tag = detail_soup.select_one("p.update")
        if not update_tag:
            continue
        m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", update_tag.get_text())
        if not m:
            continue
        items.append({
            "title": title,
            "link": link,
            "pub_str": to_pub_str(*m.groups()),
            "publisher": cfg.get("publisher", cfg["name"]),
            "source": cfg["id"],
            "category": cfg.get("category"),
        })
    if skipped:
        print(f"  (うち{skipped}件は前回と同一タイトルのため詳細取得をスキップ)")
    return items


def scrape_goguynet(cfg, existing_by_link):
    url = cfg["url"]
    soup = fetch_soup(url)
    items = []
    for box in soup.select("div.centerMdBox01"):
        a = box.select_one("a.itemTitle01[href]")
        title_tag = box.select_one("h1.itemTitle01In span")
        date_tag = box.select_one("div.listDate01 span")
        if not (a and title_tag and date_tag):
            continue
        m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", date_tag.get_text())
        if not m:
            continue
        title = title_tag.get_text(strip=True)
        category = cfg.get("category")
        if any(kw in title for kw in KAITEN_KEYWORDS):
            category = "開店・閉店"
        elif category == "鎌ヶ谷・白井" and not any(kw in title for kw in ["鎌ケ谷", "鎌ヶ谷", "白井"]):
            # 号外NETは鎌ケ谷・白井・印西の3市をカバーするため、印西市単独の記事は
            # 「鎌ヶ谷・白井」に固定せずタイトルからの推定/AI判断(review_queue)に委ねる
            category = None
        items.append({
            "title": title,
            "link": a["href"].strip(),
            "pub_str": to_pub_str(*m.groups()),
            "publisher": cfg.get("publisher", cfg["name"]),
            "source": cfg["id"],
            "category": category,
        })
    return items


HTML_SCRAPER_FUNCS = {
    "makinohara-more": scrape_makinohara,
    "aeonmall-chibanewtown-renewal": scrape_aeonmall_renewal,
    "aeonmall-chibanewtown-event": scrape_aeonmall_event,
    "goguynet-kamagaya-shiroi-inzai": scrape_goguynet,
}


# ============================================================
# RSS収集
# ============================================================

def _local_tag(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def fetch_rss(cfg, blocked_publishers):
    url = cfg["url"]
    fixed_publisher = cfg.get("publisher")
    category = cfg.get("category")
    require_local_keyword = cfg["id"].startswith("google-news-")
    items = []
    filtered_out = 0
    try:
        res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        res.raise_for_status()
        root = ET.fromstring(res.content)
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

            try:
                pub_dt = parsedate_to_datetime(pub_raw).astimezone(JST)
            except Exception:
                try:
                    pub_dt = datetime.fromisoformat(pub_raw).astimezone(JST)
                except Exception:
                    pub_dt = datetime.now(JST)

            if title and link:
                if publisher in blocked_publishers:
                    continue
                if require_local_keyword and not is_locally_relevant(title):
                    filtered_out += 1
                    continue
                link = link.replace("news.google.com/rss/articles/", "news.google.com/articles/")
                items.append({
                    "title": title,
                    "link": link,
                    "desc": desc[:200] if len(desc) > 200 else desc,
                    "pub_iso": pub_dt.isoformat(),
                    "pub_str": to_pub_str(pub_dt.year, pub_dt.month, pub_dt.day),
                    "publisher": publisher,
                    "source": cfg["id"],
                    "category": category,
                })
    except Exception as e:
        print(f"[WARN] RSS取得エラー ({url}): {e}", file=sys.stderr)
    if filtered_out:
        print(f"  ({filtered_out}件は印西と無関係と判定し除外)")
    return items


# ============================================================
# collect: 収集 + ルールベース重複排除/カテゴリ分類
# ============================================================

def collect_candidates(existing_by_link, sources):
    candidates = []
    for cfg in sources.get("html_scrapers", []):
        func = HTML_SCRAPER_FUNCS.get(cfg["id"])
        if func is None:
            print(f"[WARN] 未対応のスクレイパーID: {cfg['id']}", file=sys.stderr)
            continue
        step_start = time.monotonic()
        try:
            items = func(cfg, existing_by_link)
        except Exception as e:
            print(f"[WARN] {cfg['name']} 取得失敗: {e}", file=sys.stderr)
            continue
        print(f"{cfg['name']}: {len(items)}件取得 [{time.monotonic() - step_start:.1f}秒]")
        candidates.extend(items)

    blocked_publishers = set(sources.get("blocked_publishers", []))
    for cfg in sources.get("rss_sources", []):
        step_start = time.monotonic()
        items = fetch_rss(cfg, blocked_publishers)
        print(f"{cfg['label']}: {len(items)}件取得 [{time.monotonic() - step_start:.1f}秒]")
        candidates.extend(items)
    return candidates


def find_best_match(title, pool):
    """poolの中からtitleに最も似ているものを探す。(similarity, item) を返す"""
    best_ratio = 0.0
    best_item = None
    for other in pool:
        ratio = title_similarity(title, other.get("title", ""))
        if ratio > best_ratio:
            best_ratio = ratio
            best_item = other
    return best_ratio, best_item


def cmd_collect(args):
    sources = load_sources()
    existing_items = load_news()
    by_link = {item["link"]: item for item in existing_items}
    today = date.today()

    candidates = collect_candidates(by_link, sources)

    # 完全一致タイトルの事前重複排除(同一記事がGoogle Newsの複数クエリでヒットするケース対応)
    seen_titles = set()
    deduped_candidates = []
    exact_dup_count = 0
    for item in candidates:
        key = item["title"].strip()
        if key in seen_titles:
            exact_dup_count += 1
            continue
        seen_titles.add(key)
        deduped_candidates.append(item)
    candidates = deduped_candidates
    if exact_dup_count:
        print(f"(タイトル完全一致の重複{exact_dup_count}件を事前に除外)")

    recent_cutoff = today - timedelta(days=DUP_COMPARE_WINDOW_DAYS)
    recent_pool = [
        it for it in existing_items
        if (parse_pub_str(it.get("pub_str", "")) or today) >= recent_cutoff
    ]

    existing_queue = load_json(REVIEW_QUEUE_PATH, [])
    pending_review_links = {e["item"]["link"] for e in existing_queue}
    excluded_links = load_excluded_links()

    new_count = updated_count = unchanged_count = auto_excluded_count = skipped_pending = skipped_excluded = 0
    review_items = []
    auto_log_entries = []
    run_ts = datetime.now(JST).strftime("%Y%m%d-%H%M")

    for item in candidates:
        link = item["link"]
        prev = by_link.get(link)

        if link in pending_review_links:
            # 前回のcollectで既にreview_queueに入っており、まだ判断されていない
            skipped_pending += 1
            continue

        if prev is None and link in excluded_links:
            # 過去に除外判定済み(ルールベース/AI判断)のリンク。同じ記事がソース側に
            # 載り続けているだけなので、再度重複判定・AIレビューにはかけない
            skipped_excluded += 1
            continue

        if prev is not None:
            # 既存記事の更新(タイトル/日付の反映など)。重複判定は不要
            merged = {**prev, **item}
            merged["retention_type"] = compute_retention_type(merged)
            if merged == prev:
                unchanged_count += 1
            else:
                updated_count += 1
            by_link[link] = merged
            continue

        category = item.get("category") or guess_category_from_title(item["title"])
        item["category"] = category
        similarity, similar_item = find_best_match(item["title"], recent_pool)

        if similarity >= DUP_AUTO_EXCLUDE_THRESHOLD:
            auto_excluded_count += 1
            auto_log_entries.append({
                "run_ts": run_ts,
                "date": today.isoformat(),
                "ai_decision": "auto_exclude",
                "similarity": round(similarity, 2),
                "title": item["title"],
                "link": link,
                "similar_to": similar_item.get("title", "") if similar_item else "",
                "ai_reason": "ルールベース: 類似度80%以上のため自動除外",
            })
            continue

        needs_dedup_review = DUP_REVIEW_THRESHOLD <= similarity < DUP_AUTO_EXCLUDE_THRESHOLD
        needs_category = category is None

        if not needs_dedup_review and not needs_category:
            item["retention_type"] = compute_retention_type(item)
            by_link[link] = item
            recent_pool.append(item)
            new_count += 1
            continue

        review_items.append({
            "review_id": f"{run_ts}-{len(review_items)+1}",
            "item": item,
            "needs_dedup_review": needs_dedup_review,
            "needs_category": needs_category,
            "similarity": round(similarity, 2) if needs_dedup_review else None,
            "similar_to": similar_item.get("title", "") if (needs_dedup_review and similar_item) else None,
            "similar_to_link": similar_item.get("link", "") if (needs_dedup_review and similar_item) else None,
            "cross_check": False,
            "decision": None,
            "category_decision": None,
            "reason": None,
        })
        # 同一記事が別クエリでも出てくることがあるので、以降の候補との類似度比較対象にも加える
        recent_pool.append(item)

    merged_all = list(by_link.values())
    final_items = [it for it in merged_all if not is_expired(it, today)]
    expired_count = len(merged_all) - len(final_items)

    save_json_atomic(NEWS_PATH, final_items)
    append_ai_log(auto_log_entries)

    combined_queue = existing_queue + review_items
    if combined_queue:
        save_json_atomic(REVIEW_QUEUE_PATH, combined_queue)
    elif REVIEW_QUEUE_PATH.exists():
        REVIEW_QUEUE_PATH.unlink()

    print(
        f"\n合算: 新規{new_count} / 更新{updated_count} / 変化なし{unchanged_count} / "
        f"期限切れ{expired_count} / 自動除外(重複80%以上){auto_excluded_count} / "
        f"要AI判断(今回){len(review_items)}件 / 判断待ち(前回から){skipped_pending}件 / "
        f"除外済みスキップ{skipped_excluded}件"
    )
    if review_items:
        print(f"→ {REVIEW_QUEUE_PATH.name} を確認し、decision/category_decision を記入した上で "
              f"`python pipeline.py apply-review` を実行してください。")
    print(f"合計 {len(final_items)} 件を {NEWS_PATH} に保存しました")


# ============================================================
# apply-review: レビュー結果の反映
# ============================================================

def cmd_apply_review(args):
    queue = load_json(REVIEW_QUEUE_PATH, [])
    if not queue:
        print("review_queue.json が空です。反映すべき項目はありません。")
        return

    existing_items = load_news()
    by_link = {item["link"]: item for item in existing_items}
    today = date.today()
    run_ts = datetime.now(JST).strftime("%Y%m%d-%H%M")

    kept = excluded = pending = 0
    log_entries = []
    remaining_queue = []

    for entry in queue:
        decision = entry.get("decision")
        item = entry["item"]

        if decision not in ("keep", "exclude"):
            remaining_queue.append(entry)
            pending += 1
            continue

        if decision == "exclude":
            excluded += 1
            # 除外リンクの記憶(次回collectでの再判定スキップ)のため、理由の種別を問わず必ず記録する
            log_entries.append({
                "run_ts": run_ts,
                "date": today.isoformat(),
                "ai_decision": "exclude",
                "similarity": entry.get("similarity"),
                "title": item["title"],
                "link": item["link"],
                "similar_to": entry.get("similar_to", ""),
                "ai_reason": entry.get("reason") or "AI判断: 重複と判定",
            })
            continue

        # decision == "keep"
        category = entry.get("category_decision") or item.get("category")
        if entry.get("needs_category") and not category:
            print(f"[WARN] カテゴリ未指定のためスキップ: {item['title']}", file=sys.stderr)
            remaining_queue.append(entry)
            pending += 1
            continue

        item["category"] = category
        item["retention_type"] = compute_retention_type(item)
        by_link[item["link"]] = item
        kept += 1
        if entry.get("needs_dedup_review") or entry.get("cross_check"):
            log_entries.append({
                "run_ts": run_ts,
                "date": today.isoformat(),
                "ai_decision": "keep",
                "similarity": entry.get("similarity"),
                "title": item["title"],
                "link": item["link"],
                "similar_to": entry.get("similar_to", ""),
                "ai_reason": entry.get("reason") or "AI判断: 別記事と判定し採用",
            })

    merged_all = list(by_link.values())
    final_items = [it for it in merged_all if not is_expired(it, today)]
    expired_count = len(merged_all) - len(final_items)

    save_json_atomic(NEWS_PATH, final_items)
    append_ai_log(log_entries)

    if remaining_queue:
        save_json_atomic(REVIEW_QUEUE_PATH, remaining_queue)
    elif REVIEW_QUEUE_PATH.exists():
        REVIEW_QUEUE_PATH.unlink()

    print(f"反映結果: 採用{kept} / 除外{excluded} / 未判定(据え置き){pending} / 期限切れ{expired_count}")
    print(f"合計 {len(final_items)} 件を {NEWS_PATH} に保存しました")


# ============================================================
# build: HTML生成
# ============================================================

CATEGORY_COLORS = {
    "話題・その他":   ("#F3F4F6", "#6B7280", "#374151"),
    "イベント・文化": ("#F3E8FF", "#9333EA", "#6B21A8"),
    "市政・行政":     ("#E8F1FF", "#2563EB", "#1E3A8A"),
    "開発・暮らし":   ("#ECFDF5", "#10B981", "#065F46"),
    "開店・閉店":     ("#FEF2F2", "#EF4444", "#991B1B"),
    "鎌ヶ谷・白井":   ("#FFF7ED", "#F97316", "#9A3412"),
    "イオンモール千葉ニュータウン": ("#ECFEFF", "#06B6D4", "#155E75"),
    "牧の原モア": ("#EDE8F8", "#6B4FA7", "#3A1F6E"),
}
CATEGORY_ICONS = {
    "話題・その他": "📰", "イベント・文化": "🎉", "市政・行政": "🏛",
    "開発・暮らし": "🌱", "開店・閉店": "🏪", "鎌ヶ谷・白井": "🗺",
    "イオンモール千葉ニュータウン": "🛍", "牧の原モア": "📍",
}
SCRAPED_COLOR = ("#EDE8F8", "#6B4FA7", "#3A1F6E")
SCRAPED_ICON = "📍"
MAX_ITEMS_PER_CAT = 20
SCRAPED_MAX_ITEMS = 20
SCRAPED_MAX_DAYS = 180
CATEGORY_CUTOFF_DAYS = {"開店・閉店": 180, "イオンモール千葉ニュータウン": 180, "鎌ヶ谷・白井": 90, "牧の原モア": 180}
DEFAULT_CUTOFF_DAYS = 90

PUBLISHER_ALIASES = {"印西市": "印西市役所"}
PUBLISHER_URL_FALLBACKS = [
    ("kamagaya-shiroi-inzai.goguynet.jp", "鎌ヶ谷白井インザイ.jp"),
    ("goguynet.jp", "goguynet"),
]

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


def normalize_publisher(pub, link=""):
    if pub in PUBLISHER_ALIASES:
        return PUBLISHER_ALIASES[pub]
    if not pub:
        for domain, name in PUBLISHER_URL_FALLBACKS:
            if domain in (link or ""):
                return name
    return pub


def kaiten_label(item):
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
    d = parse_pub_str(item.get("pub_str", ""))
    data_pub = (' data-pub="' + d.isoformat() + '"') if d else ""
    title = kaiten_label(item)
    return (
        '<a class="news-item"' + data_pub + ' href="' + html.escape(item["link"]) + '" target="_blank" rel="noopener">'
        + '<span class="news-title">' + html.escape(title) + "</span>"
        + '<span class="news-date">' + html.escape(item.get("pub_str", "")) + pub_html
        + '<span class="today-badge" style="display:none">今日</span></span>'
        + "</a>"
    )


def build_html(articles):
    now = datetime.now(JST)
    now_str = f"{now.year}年{now.month}月{now.day}日 {now.strftime('%H:%M')}"
    today = now.date()
    cutoff = today - timedelta(days=SCRAPED_MAX_DAYS)

    main_arts_all = [a for a in articles if a.get("category") in CATEGORY_ORDER]
    scraped_arts = [a for a in articles if a.get("category") not in CATEGORY_ORDER]

    def date_ok(item):
        d = parse_pub_str(item.get("pub_str", ""))
        if not d:
            return True
        days = CATEGORY_CUTOFF_DAYS.get(item.get("category", ""), DEFAULT_CUTOFF_DAYS)
        return d >= today - timedelta(days=days)

    main_arts = [a for a in main_arts_all if date_ok(a)]
    main_arts.sort(key=lambda a: parse_pub_str(a.get("pub_str", "")) or date.min, reverse=True)
    top_item = main_arts[0] if main_arts else None

    if top_item:
        cat = top_item.get("category", "話題・その他")
        _, fg, _ = CATEGORY_COLORS.get(cat, CATEGORY_COLORS["話題・その他"])
        top_pub = normalize_publisher(top_item.get("publisher", ""), top_item.get("link", ""))
        pub_h = " · " + html.escape(top_pub) if top_pub else ""
        hero_d = parse_pub_str(top_item.get("pub_str", ""))
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

    active_cats = [(cat, cat_map.get(cat, [])[:MAX_ITEMS_PER_CAT]) for cat in CATEGORY_ORDER if cat_map.get(cat)]
    grid_html = ""
    for cat, items in active_cats:
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
        scraped_map[item.get("category") or "地域情報"].append(item)

    scraped_html = ""
    for site, items in scraped_map.items():
        items = sorted(items, key=lambda a: parse_pub_str(a.get("pub_str", "")) or date.min, reverse=True)
        filtered = [i for i in items if (parse_pub_str(i.get("pub_str", "")) or cutoff) >= cutoff][:SCRAPED_MAX_ITEMS]
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


def cmd_build(args):
    articles = load_news()
    print(f"{len(articles)}件の記事でHTMLを生成中...")
    content = build_html(articles)
    INDEX_HTML_PATH.write_text(content, encoding="utf-8")
    print(f"index.html を生成しました → {INDEX_HTML_PATH}")


# ============================================================
# publish: git push
# ============================================================

def cmd_publish(args):
    if not TOKEN_PATH.exists():
        print("エラー: .gh_token が見つかりません。git pushをスキップします。", file=sys.stderr)
        sys.exit(1)
    token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    repo_dir = str(BASE_DIR)
    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")

    def run(cmd, **kw):
        return subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, **kw)

    run(["git", "config", "user.name", "claude-code-bot"])
    run(["git", "config", "user.email", "claude-code-bot@users.noreply.github.com"])
    run(["git", "add", "-A"])
    r = run(["git", "commit", "-m", f"ニュース更新: {now_str}"])
    if r.returncode != 0:
        if "nothing to commit" in (r.stdout + r.stderr):
            print("変更なし。pushをスキップします。")
            return
        print(f"エラー(commit): {r.stderr}", file=sys.stderr)
        sys.exit(1)

    push_url = f"https://{token}@github.com/{GITHUB_REPO}.git"
    plain_url = f"https://github.com/{GITHUB_REPO}.git"
    try:
        run(["git", "remote", "set-url", "origin", push_url])
        r = run(["git", "push"])
        if r.returncode != 0:
            print(f"エラー(push): {r.stderr}", file=sys.stderr)
            sys.exit(1)
    finally:
        run(["git", "remote", "set-url", "origin", plain_url])
    print("git push 完了")


# ============================================================
# 開店閉店情報の管理
# ============================================================

def load_store_lines():
    text = STORE_LIST_PATH.read_text(encoding="shift_jis")
    return [line.strip() for line in text.splitlines() if line.strip()]


def save_store_lines(lines):
    body = "\n".join(lines) + ("\n" if lines else "")
    STORE_LIST_PATH.write_text(body, encoding="shift_jis")


def latest_event_date(name, news_items):
    dates = []
    for item in news_items:
        if name not in item.get("title", ""):
            continue
        m = STORE_EVENT_TITLE_PATTERN.match(item["title"])
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            dates.append(date(y, mo, d))
    return max(dates) if dates else None


def cmd_store_pending(args):
    if not STORE_LIST_PATH.exists():
        print(f"{STORE_LIST_PATH.name} が見つかりません。")
        return
    lines = load_store_lines()
    news_items = load_news()
    cutoff = months_ago(date.today(), STORE_EVENT_RETENTION_MONTHS)

    kept_lines, pending, done, starred, expired = [], [], [], [], []
    for line in lines:
        if line.startswith("★"):
            starred.append(line[1:].strip())
            kept_lines.append(line)
            continue
        event_date = latest_event_date(line, news_items)
        if event_date is None:
            pending.append(line)
            kept_lines.append(line)
        elif event_date < cutoff:
            expired.append(line)
        else:
            done.append(line)
            kept_lines.append(line)

    if expired:
        save_store_lines(kept_lines)

    print(f"未処理: {len(pending)}件")
    for name in pending:
        print(f"  - {name}")
    print(f"処理済み(スキップ): {len(done)}件")
    print(f"★スキップ対象: {len(starred)}件")
    if expired:
        print(f"6か月経過のため開店閉店.txtから削除: {len(expired)}件")
        for name in expired:
            print(f"  - {name}")


def cmd_store_add(args):
    news_items = load_news()
    by_link = {item["link"]: item for item in news_items}
    label = {"開店": "開店", "閉店": "閉店", "リニューアル": "リニューアル"}[args.type]
    title = f"【{args.date} {label}】{args.store}"
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", args.date)
    if not m:
        print("エラー: --date は 'YYYY年M月D日' 形式で指定してください", file=sys.stderr)
        sys.exit(1)
    item = {
        "title": title,
        "link": args.link,
        "pub_str": args.date,
        "publisher": args.publisher or "",
        "source": "開店閉店情報",
        "category": "開店・閉店",
        "desc": args.desc or "",
    }
    item["retention_type"] = compute_retention_type(item)
    by_link[args.link] = item
    today = date.today()
    final_items = [it for it in by_link.values() if not is_expired(it, today)]
    save_json_atomic(NEWS_PATH, final_items)
    print(f"登録しました: {title}")


def cmd_store_star(args):
    if not STORE_LIST_PATH.exists():
        print(f"{STORE_LIST_PATH.name} が見つかりません。")
        return
    lines = load_store_lines()
    new_lines = []
    matched = False
    for line in lines:
        bare = line[1:].strip() if line.startswith("★") else line
        if bare == args.store:
            new_lines.append(f"★{bare}")
            matched = True
        else:
            new_lines.append(line)
    if not matched:
        print(f"'{args.store}' が開店閉店.txt に見つかりませんでした。", file=sys.stderr)
        sys.exit(1)
    save_store_lines(new_lines)
    print(f"★を付与しました: {args.store}")


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="印西ニュース 統合パイプライン")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("collect", help="ソース収集 + ルールベース処理").set_defaults(func=cmd_collect)
    sub.add_parser("apply-review", help="review_queue.jsonの反映").set_defaults(func=cmd_apply_review)
    sub.add_parser("build", help="index.html生成").set_defaults(func=cmd_build)
    sub.add_parser("publish", help="git push").set_defaults(func=cmd_publish)
    sub.add_parser("store-pending", help="開店閉店.txtの未処理店舗一覧").set_defaults(func=cmd_store_pending)

    p_add = sub.add_parser("store-add", help="開店閉店情報を1件登録")
    p_add.add_argument("--store", required=True)
    p_add.add_argument("--date", required=True, help="YYYY年M月D日")
    p_add.add_argument("--type", required=True, choices=["開店", "閉店", "リニューアル"])
    p_add.add_argument("--link", required=True)
    p_add.add_argument("--publisher", default="")
    p_add.add_argument("--desc", default="")
    p_add.set_defaults(func=cmd_store_add)

    p_star = sub.add_parser("store-star", help="開店閉店.txtの店舗に★を付与")
    p_star.add_argument("--store", required=True)
    p_star.set_defaults(func=cmd_store_star)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
