# 印西ニュース プロジェクト

千葉県印西市のニュースまとめサイトを収集・生成・公開する統合プロジェクト。
旧「Claude Code（ローカル）＋Claude Desktop Cowork（クラウド）」の分散構成を廃止し、Claude Code単一プロジェクトに統合した（詳細: `印西ニュース_新プロジェクト仕様書.md`）。

## サイト情報
- URL: https://inzai-news.github.io/news/
- GitHubリポジトリ: https://github.com/inzai-news/news （このフォルダがそのままclone元）
- GA4測定ID: G-89CXHHR0XZ

## ファイル構成
- `sources.json` — 収集元の一元定義（HTMLスクレイピング7件＋RSS11件）
- `pipeline.py` — 収集・重複排除・カテゴリ分類・HTML生成・git publishの統合スクリプト
- `news.json` — 統合ニュースデータ（公開対象、gitで管理）
- `review_queue.json` — AI判断待ちの記事キュー（gitignore対象、判断後は空になり削除される）
- `ai_check_log.json` — 重複判定AIログ（後から閾値の妥当性を検証するため。加えて、除外(exclude/auto_exclude)済みリンクの記憶としても使われ、`collect`実行時に一度除外判定した記事を再度重複判定・AIレビューにかけないようにする）
- `new_badge.json` — 「新着」バッジ対象リンクの一覧（gitで管理）。`collect`で新規記事(ルールベース採用分)が出たら今回分で上書き、`apply-review`でAI判断の採用が出たら直前のcollect分に合流(union)させる。どちらも0件だった回は一切触らないため、更新が無い回は前回の「新着」がそのまま残り続ける
- `開店閉店.txt`（Shift-JIS） — 開店閉店情報の調査対象店舗リスト（gitignore対象、ローカルのみ）
- `.gh_token` — GitHub Fine-grained PAT（gitignore対象）
- `index.html` — 生成物（GitHub Pagesで配信）
- `weather_icons/` — ウェザーニューズの天気アイコン画像キャッシュ（gitで管理、`build`時に無いものだけ自動ダウンロード）
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
6. 最終的な件数サマリを以下のフォーマットでユーザーに報告する。数値は`collect`の出力（取得記事件数/新規の記事件数/タイトル完全一致の重複{exact_dup_count}/更新{updated_count}/変化なし{unchanged_count}/新規{new_count}/自動除外(重複80%以上){auto_excluded_count}/判断待ち{skipped_pending}/除外済みスキップ{skipped_excluded}/新規だが掲載期限切れ{expired_new_count}）と`apply-review`の出力（採用{kept}/除外{excluded}）から組み立てる。

```
======================================

取得記事件数    ：{collectの「取得記事件数」}

(内訳)
新規の記事件数  ：{collectの「新規の記事件数」}
既出記事件数    ：{collectの「更新」+「変化なし」の合計}
重複記事件数    ：{collectの「タイトル完全一致の重複」件数}

(新規採用詳細)
新規採用件数    ：{collectの「新規」+ apply-reviewの「採用」の合計}
内AI判定採用件数：{apply-reviewの「採用」件数}

(除去内訳)
80%類似除去件数 ：{collectの「自動除外(重複80%以上)」件数}
AI判定除去件数  ：{apply-reviewの「除外」件数}
期限切れ除去件数：{collectの「新規だが掲載期限切れ」件数}
その他除去件数  ：{collectの「判断待ち(前回から)」+「除外済みスキップ」の合計}

======================================
```

検算: 「取得記事件数」＝「新規の記事件数」＋「既出記事件数」＋「重複記事件数」。
また「新規の記事件数」＝「新規採用件数」＋「80%類似除去件数」＋「AI判定除去件数」＋「期限切れ除去件数」＋「その他除去件数」で一致するはず。
「重複記事件数」は、同一記事が複数のGoogle News検索クエリに重複してヒットした分（`collect`実行時に「タイトル完全一致の重複」として画面に表示される）。
「期限切れ除去件数」は、Google News等から拾われた記事が実際には掲載期限(通常記事3か月/開店閉店6か月)を超えた過去記事の再ヒットだったケース。追加と同時に自動除外され、`ai_check_log.json`に記録されるため次回以降は「除外済みスキップ」に回る。

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
- **天気予報表示**: `build`実行時にウェザーニューズ(`weathernews.jp/onebox/tenki/chiba/12231/week.html?tab=4`)から印西市の今日・明日・明後日の3日分をスクレイピングし、時刻に応じて2日分(22時未満は今日・明日、22時以降は明日・明後日)をヒーロー記事の横に表示する(クリックで同サイトの日次ページ`?tab=3`へ遷移)。このページはVue.js製だがサーバー側で実データがHTMLに埋め込まれているため、JS実行なしで取得可能。今日・明日は`#flick_list_today`内の`div.card`から天気文言・最高/最低気温・降水確率を取得し、明後日は`#flick_list_week`内の行から気温・アイコンのみ取得する(天気文言・降水確率%はこのセクションには無い)。アイコンは絵文字ではなくウェザーニューズの実画像(`wxicon/*.png`)を`weather_icons/`にキャッシュして使い回す(同名ファイルがあれば再ダウンロードしない)。ファイル名は`{コード}_{天気名}.png`(天気文言が取れない場合は`{コード}.png`)。取得失敗時は全体を静かにスキップし、ビルド自体は失敗しない。`news.json`には保存されない（build時の都度取得）。旧実装(Open-Meteo API)は精度への不満から2026-07-20に置き換えた。2026-07-20にウェザーニューズ公式のアイコン一覧ページ(`weathernews.jp/ip/help5/tab_icon.html`)を参照し、掲載されていた33種類のコードを`weather_icons/`へ先取りキャッシュ済み(ラベル付き)。
- **event_end_date（イベント開催終了日）**: `event_end_date`（ISO形式、複数日開催なら最終日）を持つ記事はカテゴリを問わず、通常の掲載期限（3か月/6か月）によらず開催終了日+3日（`EVENT_END_GRACE_DAYS`）を過ぎたら`collect`実行時に削除対象となる（`is_expired()`が優先判定）。新規記事として拾った時点で既に開催終了日+3日を過ぎている場合も同様に除外される。現状この値を設定しているのは「ジョイフル本田千葉ニュータウン店」カテゴリのスクレイパーのみ。日付が取得できなかった記事は通常の掲載期限ロジックにフォールバックする。
