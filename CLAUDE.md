# 印西ニュース プロジェクト

千葉県印西市のニュースまとめサイトを収集・生成・公開する統合プロジェクト。
旧「Claude Code（ローカル）＋Claude Desktop Cowork（クラウド）」の分散構成を廃止し、Claude Code単一プロジェクトに統合した（詳細: `印西ニュース_新プロジェクト仕様書.md`）。

## サイト情報
- URL: https://inzai-news.github.io/news/
- GitHubリポジトリ: https://github.com/inzai-news/news （このフォルダがそのままclone元）
- GA4測定ID: G-89CXHHR0XZ

## ファイル構成
- `sources.json` — 収集元の一元定義（HTMLスクレイピング4件＋RSS8件）
- `pipeline.py` — 収集・重複排除・カテゴリ分類・HTML生成・git publishの統合スクリプト
- `news.json` — 統合ニュースデータ（公開対象、gitで管理）
- `review_queue.json` — AI判断待ちの記事キュー（gitignore対象、判断後は空になり削除される）
- `ai_check_log.json` — 重複判定AIログ（後から閾値の妥当性を検証するため）
- `開店閉店.txt`（Shift-JIS） — 開店閉店情報の調査対象店舗リスト（gitignore対象、ローカルのみ）
- `.gh_token` — GitHub Fine-grained PAT（gitignore対象）
- `index.html` — 生成物（GitHub Pagesで配信）
- `参考/` — 旧Cowork/Code両系統の実体一式（gitignore対象、移行が落ち着いたら削除してよい）

## 「ニュース更新して」と言われた場合の手順

1. `python pipeline.py collect` を実行する。ルールベースで判定可能な記事は自動的に `news.json` に反映され、件数サマリ（新規/更新/変化なし/期限切れ/自動除外/要AI判断）が表示される。
2. `review_queue.json` が生成されたら中身を読み、エントリごとに次を判断する:
   - `needs_dedup_review: true` → `similar_to`（既存採用記事のタイトル）と見比べ、同一ニュースの重複記事なら `decision: "exclude"`、別ニュースなら `decision: "keep"` を記入する。判断が難しい場合はリンク先を実際に開いて内容を確認してよい。`reason` に一言理由を書く。
   - `needs_category: true` → 記事のタイトル・publisher・linkから最も適切なカテゴリを判断し `category_decision` に設定する。カテゴリは以下の7つのいずれか:
     `話題・その他` / `イベント・文化` / `市政・行政` / `開発・暮らし` / `開店・閉店` / `鎌ヶ谷・白井` / `イオンモール千葉ニュータウン`
   - 両方trueの場合は両方判断する。判断が付かない記事は `decision` を空のままにしてよい（次回実行まで据え置かれる）。
   - 判断を書き込んだら `review_queue.json` をEditツールで上書き保存する。
3. `python pipeline.py apply-review` を実行し、判断結果を `news.json` に反映する（`ai_check_log.json` にも記録される）。
4. `python pipeline.py build` で `index.html` を生成する。
5. `python pipeline.py publish` で git add/commit/push する。
6. 最終的な件数サマリ（新規/更新/変化なし/期限切れ/自動除外/AI採用/AI除外）をユーザーに報告する。

対話実行・CronCreateスケジュール実行のどちらでもこの手順は共通。スケジュール実行時はグレーゾーン判定・カテゴリ分類を自分（Claude）の裁量で判断してよい（ユーザー確認は不要）。

## 「開店閉店.txt更新したので処理して」と言われた場合の手順

1. `python pipeline.py store-pending` で未処理店舗一覧を取得する（6か月経過した処理済み店舗は自動的にtxtから削除される）。
2. 各店舗についてWeb検索で開店/閉店情報を調査する。
3. 情報が見つかったら `python pipeline.py store-add --store "店名" --date "YYYY年M月D日" --type 開店|閉店|リニューアル --link "URL" --publisher "情報源名"` で登録する（`news.json` に `category: 開店・閉店`, `retention_type: store_event`（6か月保存）として追加される）。
4. 特定できなかった店舗は `python pipeline.py store-star --store "店名"` で★を付け、以後の調査対象から外す。
5. 処理後、続けて通常の更新手順（1〜6）を流すかユーザーに確認する。

## CronCreateスケジュールについて

- VSCode/Claude Code起動中のみ有効。**7日で自動失効する**ため、失効が近い（3日以内）場合はセッション開始時にユーザーへ知らせ、再登録（「スケジュール再開して」等の指示を待つか、明示的な許可を得た上でCronCreateを再実行）を促すこと。
- スケジュールの内容は「ニュース更新して」の手順（上記）と同一。無人実行のため、グレーゾーン判定・カテゴリ分類はClaude自身の判断で進めてよい。
- 外部Anthropic APIキーは使用しない。追加課金は発生しない。

## 既知の制約

- **Google News URL解決は不可能**: `news.google.com/rss/articles/...` は実際のニュースサイトへリダイレクトを解決できない（bot対策）。`/rss/articles/` → `/articles/` への文字列変換のみ行い、リンク先がGoogle Newsのままであることを許容する。
- **paywallチェック機能は持たない**: 旧`articles_cache.json`は前述の制約により実質機能していなかったため廃止した。
- **標準出力バッファリング**: `pipeline.py`は `sys.stdout.reconfigure(line_buffering=True)` を維持している。
- **アトミック書き込み**: JSON保存は一時ファイル＋`os.replace`＋読み直し検証の方式（`save_json_atomic`）を維持している。
- **開店閉店.txtの文字コード**: Shift-JIS。読み書きは必ずこのエンコーディングで行う（`pipeline.py`側で対応済み）。
- **既存データの移行**: 2026-07-16の再構築時、旧`news.json`等の既存データは引き継がず空から再収集を開始した。
