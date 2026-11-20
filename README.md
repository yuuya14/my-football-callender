# サッカー日程カレンダー（iPhone購読用）

Man Utd のチャンピオンズリーグ・カラバオカップ・FAカップと、浦和レッズの J1・ルヴァンカップ・天皇杯の日程を、
iPhone の「照会カレンダー」として購読できる .ics にするための仕組みです。

```
data/*.csv          ← 日程データ（ここだけ編集すればOK）
calendars.json      ← カレンダー名・タイムゾーン・タイトル先頭の絵文字（title_prefix）等の設定
build_ics.py        ← CSV → .ics 変換スクリプト
docs/*.ics          ← 生成されたカレンダー（公開・購読される本体）
docs/index.html     ← iPhoneでタップして登録するためのページ
.github/workflows/  ← CSVを更新すると自動で .ics を作り直す設定
```

## 1. 初回セットアップ（GitHub Pages で公開）

1. GitHub で **Public** リポジトリを新規作成（例: `football-calendar`）
2. このフォルダの中身をすべてアップロード（`.github` フォルダも含む）
   - ブラウザの場合：リポジトリ画面の「Add file → Upload files」にフォルダごとドラッグ
3. リポジトリの **Settings → Pages** で
   - Source: `Deploy from a branch`
   - Branch: `main` / フォルダ: `/docs` → Save
4. **Settings → Actions → General → Workflow permissions** を `Read and write permissions` にして Save
5. 数分後、`https://<ユーザー名>.github.io/football-calendar/` が開けるようになります

## 2. iPhone で購読

1. iPhone の Safari で上記URLを開く
2. 登録したいカレンダーをタップ →「照会」を許可 → 「追加」
3. 色や通知は「カレンダー」アプリ → カレンダー一覧 → ⓘ から変更できます

※ Safari でうまく開かない場合は「URLをコピー」→ 設定アプリ → カレンダー → アカウント →
アカウントを追加 → その他 → 照会するカレンダーを追加 → URLを貼り付け、でも登録できます。

## 3. 日程の更新（キックオフ時刻決定・来シーズン以降）

GitHub 上で `data/*.csv` を編集して保存（Commit）するだけです。
GitHub Actions が自動で .ics を作り直し、iPhone 側にも数時間以内に反映されます。
**購読URLは変わらないので、iPhone の再登録は不要**です。

| やりたいこと | CSVの直し方 |
|---|---|
| キックオフ時刻が決まった | `time` に `19:00` のように入力 |
| 「土 or 日」の日付が確定した | `date` を確定日にして `date_alt` を空にする |
| 試合結果を入れたい | `result` に `○2-1` など（任意） |
| 勝ち上がりで対戦相手が決まった | `home`/`away`/`venue` を入力し、`status` を `confirmed` に |
| 来シーズンにする | 行を新シーズンの日程に差し替え、`id` を `2027-28-r01` のように変える |

- `id` を変えなければ、日時を修正しても「同じ予定の更新」として扱われます（重複しません）
- `time` は**現地時間**で入力します（UCL は英国時間。iPhone では日本時間に自動変換されます）
- 時刻が空欄の試合は「終日予定」として入ります

### ローカルで編集して push する場合の注意

push のたびに GitHub Actions が `docs/*.ics` を作り直してコミットするため、
**作業を始める前に必ず `git pull` してください**（しないと push が rejected になります）。

```bash
cd ~/Documents/Github/football-calendar
git pull            # ← 最初に必ず
# CSVなどを編集
git add . && git commit -m "日程更新" && git push
```

## 4. タイトル先頭の絵文字を変える

`calendars.json` の `"title_prefix": "⚽️"` を書き換えます（空にすれば絵文字なし）。
特定のカレンダーだけ変えたい場合は、そのカレンダーの設定に `"title_prefix": "🏆"` のように追加します。

## 5. ローカルで生成する場合

```bash
python3 build_ics.py   # Python 3.9以上、追加ライブラリ不要
```
