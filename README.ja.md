# 韓国税関貿易 2012–2026 — HSK 10桁商品レベル

[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

![Korea Customs Trade banner](assets/korea_customs_trade_readme_banner.jpg)

[データモデル / リリース構成](DATA_MODEL.md)

このリポジトリは、韓国関税庁（Korea Customs Service）の公式公開データを基に、再現可能な Kaggle データプロダクトを構築します。Source of Truth とする粒度は次のとおりです。

`month × partner_country × HSK10`

最終データセットでは韓国の **10桁 HSK** を完全な粒度で保持し、`hs8`、`hs6`、`hs4`、`hs2` は各集計レベルを別途収集するのではなく、HSK10 の接頭辞からローカルで派生させます。

## 現在のフェーズ

API pilot、国コード参照の検証、production collector、normalization pipeline、全期間 historical backfill、公式年次 HSK reference の収集、release QA、private-first Kaggle 検証、Public Dataset 公開、Public starter Notebook 公開、そして **Kaggle Usability 10.00** の達成まで完了しています。最初に検証した中心仮説は次のとおりです。

> `cntyCd` と期間を指定し、`hsSgn` を省略した場合、韓国関税庁の品目別・国別 API はその国の月次 HSK10 貿易行をすべて返すか？

最初の live test は **US × 2025** でした。完了した pilot matrix は次のとおりです。

- 国: `US`, `CN`, `JP`, `VN`, `DE`
- 年: `2012`, `2017`, `2022`, `2025`

この gate を通過した後に full crawl を開始し、historical backfill は現在完了しています。

### ロードマップ進捗

現在のステージは **12/12 — Public Kaggle release 公開済み、Usability 10.00 達成**です。full historical backfill は予定していた 4,035/4,035 の country-year root をすべて完了し、未解決失敗は 0、収集された fact row は 22,351,483 行です。Stage 11 では strict HSK10 22,351,430 行に加えて、53 行の non-HSK10 source exception を保持し、canonical key の重複は 0、`release_gate_pass=true` です。2012–2026 の公式 CLIP 年次 HSK reference は 178,911 annual HSK10 rows を含み、韓国語・英語の商品名は完全に揃っており、未解決の duplicate-label review はありません。

Kaggle Dataset `taeyangg4/south-korea-customs-trade-hsk10` は **Public**、Version 2 は `Ready`、観測された Usability は **10.00/10** です。Public starter Notebook `taeyangg4/south-korea-trade-in-5-minutes-hs6-quickstart` は Version 3 まで到達し、Kaggle runtime 上で Dataset mount の自動検出、traceback なし、韓国語 glyph warning なしで正常完了しました。Kaggle Usability の詳細確認では file description と column description を含むすべての score component が `1` です。

さらに二つの Public 分析プロジェクトで、リリースの高度な利用例を示しています。`taeyangg4/korea-import-dependency-hsk10-supply-chain`（Version 2、`COMPLETE`）は直近 12 か月の HSK10 輸入について Top-1/Top-3 share、HHI、concentration-weighted import exposure を算出します。`taeyangg4/forecast-korea-imports-hs6-ml-vs-naive`（Version 3、`COMPLETE`）は、学習期間のみで選択した上位 100 HS6 輸入グループを対象に、時系列 leakage を避けた機械学習 benchmark を行います。現在の 2025-08〜2026-07 holdout では、Huber loss を使う Gradient Boosting が WAPE を **seasonal naive 比 34.0%**、**lag-1 persistence 比 8.4%** 改善し、その後すべての利用可能月で再学習して 2026-08 の one-step-ahead forecast を生成します。これらの benchmark 値は現在の Dataset version に対応するため、今後の月次 refresh 後には変化します。

最終的なプロダクト目標は **Kaggle Usability 10.00 + Dataset medal** です。公式 source data を過度にクリーニングせず、再現性、分析しやすい grain、文書化、更新可能性、韓国語テキストの encoding 安全性を重視します。

pilot matrix では小さいながら重要な upstream data-quality exception も確認されました。1,379,734 fact rows のうち 5 行が 10 桁 HSK ではなく、4 行が 6 桁、1 行が 9 桁でした。対象コードを API で再照会しても同じ結果が再現されたため parser error ではありません。これらは raw XML に保存し、`non_hs10_rows.csv` に隔離します。canonical HSK10 fact table で 10 桁へ zero-padding したり推測変換したりすることはありません。

公式 KCS lookup workbook から現在 **269 個の一意な国コード**を取得しています。269 コードすべてを 2025-01 API で live validation した結果、すべて受理され、236 コードにはその月の貿易行があり、33 コードは取引なしでした。全コードの 1 月 census では **128,207 fact rows** があり、すべて numeric HSK10 でした。full-history の計画規模はおよそ **2,200万〜3,500万行**、adaptive split 前の production root-request 数は **4,035**（269 codes × 15 calendar-year windows）です。

最終 Stage-11 partitioned output は HSK10 **22,351,430 rows / 441,335,631 bytes**、HS8 **20,576,865 / 353,521,769**、HS6 **16,059,132 / 257,080,829**、HS4 **7,234,105 / 124,721,647**、HS2 **1,446,045 / 29,122,656** です。5 レベルすべてが 2012-01〜2026-07 の 175 monthly partitions を持ちます。

Stage 11 は次のコマンドで再現できます。

```powershell
.\run_stage11.ps1
```

この処理は full country-month coverage を要求し、annual HSK revision をリンクし、HS8/HS6/HS4/HS2 の residual-aware analyst table を構築し、韓国語テキストおよび UTF-8 の release gate を実行します。

Kaggle 向け package は次のコマンドで作成します。

```powershell
.\run_build_release.ps1
```

Git Bash では `bash ./run_build_release.sh` を使用できます。release builder は analytical grain ごとに統合 Parquet を 1 ファイル、最新月 HS6 CSV preview、reference/audit file、checksum、完全な Kaggle file/column metadata、provenance、documentation を Git から除外された `release/kaggle/` に書き出します。

国コード authority policy:

- `country_code` と `country_name_ko`: 韓国関税庁 `관세청조회코드_v1.3.xlsx`
- English/M49/alpha3 enrichment: UN Statistics Division M49 の alpha-2 完全一致のみ
- 一致しない KCS code は英語名/UN field を空欄のまま保持し、削除や推測は行いません

## Revision-aware HSK reference

Stage 10 では、韓国関税庁 CLIP の韓国関税率表を historical HSK reference として使用します。サイトはプロジェクト対象期間の年次版韓国関税率表を公開し、韓国語・英語の商品名を含む階層型 tariff row を返します。

ローカル reference builder は CLIP の raw HTML を年/類ごとに cache し、cache から resume し、正確な numeric HSK10 row のみを parse して年次および統合 Parquet reference data を生成します。

```powershell
python .\hsk_reference.py probe --year 2022 --chapter 01
.\run_hsk_reference.ps1
```

最初の live probe では 2022 年第 01 類から 69 HSK10 rows を parse し、韓国語名・英語名の欠損はありませんでした。2012–2026 全期間の収集も完了しており、178,911 annual HSK10 rows、韓国語名欠損 0、英語名欠損 0、annual key 重複 0、prefix mismatch 0 を確認しています。同一コードの source label variant は 3 件観測され、2012 年の 2 件はより具体的な compatible wording を優先して解決し、2022 年の revision-boundary conflict 1 件は 2021/2023 edition と自動比較して解決しました。`HSK-YYYY` は公式 CLIP の **年次版**を意味し、年次 selector から確認できない年内の法的改正境界は推測しません。

## Production collector

大規模収集の前に full plan を dry-run します。

```powershell
python .\collector.py --dry-run backfill
```

2026-09-08 時点では `201201–202607`、269 国コード、15 calendar-year windows、**4,035 root requests** に解決されます。現在の stable-month rule は 15 日を過ぎた場合のみ前月を使用し、それ以前は 2 か月前を使用します。

完了済みの full backfill は次のコマンドで再現できます。

```powershell
.\run_backfill.ps1
```

monthly revision refresh mode は最新 stable month とその前 12 か月を再取得します。

```powershell
.\run_refresh.ps1
```

smoke test には `--countries`、`--max-roots`、`--dry-run` を使用できます。production run manifest は `data/audits/runs/` に書かれ、service key は含みません。

## 公式 API

- 韓国関税庁 品目別・国別 輸出入実績 (GW)
- Endpoint: `https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList`
- 主なパラメータ: `serviceKey`, `strtYymm`, `endYymm`, `cntyCd`
- pilot では `hsSgn` を意図的に省略します

## Pilot が記録する内容

各 request は raw response を保持し、audit と resume に必要な metadata を記録します。

- HTTP status と API result code/message
- exact response bytes と SHA-256
- gzip 圧縮 raw XML
- item 数と fact-row 数
- 観測された HS-code length distribution
- numeric 10-digit HSK compliance
- requested-month coverage
- duplicate `(month, country, hs10)` keys
- zero-trade rows
- negative amount/weight rows
- `trade_balance == export - import` reconciliation
- country-code mismatch
- 観測された韓国語 HSK-name variant
- elapsed time と retry count

data.go.kr service key は manifest に書き込みません。

## Adaptive request splitting

論理的な収集単位は `country × year` です。retry 可能な transport failure は自動的に次のように分割します。

```text
country × year
  -> country × quarter
      -> country × month
```

authentication、parameter、API-level error は splitting で隠しません。

## API quota 戦略

公式 data.go.kr ページでは現在、development account の上限として **1 日 10,000 requests** が示されています。同ページには、利用事例登録後に **operating account で traffic increase を申請できる**ことも記載されており、この Korea Customs API は operating stage で審査が必要です。

このプロジェクトでは quota を保守的に管理します。

- 成功する場合は `country × calendar-year window` 1 request を優先します。公式 reference では現在 269 codes × 15 windows = **4,035 root requests** です。
- 成功する request を事前に quarter/month へ分割しません。adaptive split は oversized response や timeout の fallback に限定します。
- data.go.kr が gateway reason code `22` (`LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR`) を返した場合、collector は無駄な追加 call をせず即時停止します。成功済み manifest は resume に利用できます。
- pilot の結果、adaptive split により 1 日 10,000 call を超える可能性がある場合は、production backfill の前に operating account / traffic increase を申請します。
- platform limit を回避する目的で複数の個人 account や key を使用しません。

公開 file dataset `관세청_월별_품목별_국가별 수출입실적` は補助的な公式 reference として有用ですが、公開説明上の範囲は 2021–2023 の HS4 であるため、本プロジェクトの HSK10 Source of Truth の代替にはなりません。

## Windows PowerShell でのセットアップ

```powershell
cd H:\dev\kaggle-data\korea-customs-trade
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:KCS_SERVICE_KEY='YOUR_DATA_GO_KR_SERVICE_KEY'
```

または、project root のローカル `.env` file に次のように記述できます。

```text
KCS_SERVICE_KEY=YOUR_DATA_GO_KR_SERVICE_KEY
```

process environment に key がない場合、collector は `.env` を自動で読み込みます。`.env` は Git から除外されています。

最初の pilot を実行します。

```powershell
.\run_us_2025.ps1
```

pilot report を確認した後で matrix を実行します。

```powershell
.\run_matrix.ps1
```

## Linux / macOS でのセットアップ

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export KCS_SERVICE_KEY='YOUR_DATA_GO_KR_SERVICE_KEY'
./run_us_2025.sh
```

## 出力構成

```text
data/
  raw/
    year=2025/
      country=US/
        response_202501-202512.xml.gz
  normalized/
    hs10/
      year=2025/
        mm=01/
          part-00000.parquet
  derived/
    hs8/year=2025/mm=01/part-00000.parquet
    hs6/year=2025/mm=01/part-00000.parquet
    hs4/year=2025/mm=01/part-00000.parquet
    hs2/year=2025/mm=01/part-00000.parquet
  audits/
    manifests/
      year=2025/
        country=US/
          request_202501-202512.json
    coverage/
      pilot_results.json
      pilot_results.csv
      pilot_report.md
      hs_name_inventory.csv
      hs_name_changes.csv
    normalization/
      source_selection.csv
      normalization_manifest.json
      normalization_anomalies.csv
    derivation/
      derivation_manifest.json
```

raw data と生成 data は既定で Git から除外されます。GitHub には code、configuration template、documentation、再現可能な pipeline logic を保存し、service key や大容量 raw response は保存しません。

## Tests

```powershell
pytest -q
```

## Pilot release gate

論理的な country-year は、すべての effective leaf request が成功し、少なくとも 1 fact row が返り、すべての fact row が numeric 10-digit HS code を持ち、requested month がすべて存在し、duplicate `(month, country, hs10)` key がない場合にのみ `PASS` になります。

pilot の `PASS` は、テストした request で観測された API behavior を検証するものです。historical HSK-code completeness まで証明するものではありません。Public release には独立した公式 aggregate と revision-aware HSK codebook による reconciliation が引き続き必要です。

## Canonical fact schema

```text
month
country_code
hs10
hs8
hs6
hs4
hs2
export_usd
export_weight_kg
import_usd
import_weight_kg
trade_balance_usd
hs_revision
```

`month` は `YYYYMM` で保存します。`hs8`、`hs6`、`hs4`、`hs2` は `hs10` の strict prefix です。`hs_revision` は該当する公式年次 KCS CLIP edition にコードが存在する場合のみ設定し、一致しない trade fact は削除・推測せず null revision のまま audit 対象として保持します。

normalization は重複する raw request があっても、各 `(country, month)` について最新の successful manifest を独立に選択します。monthly revision refresh で古い row が新しい source から消えた場合、その row は rebuilt normalized dataset からも消え、stale な append-only row として残りません。

長期的な release architecture は [`DATA_MODEL.md`](DATA_MODEL.md) に記載しています。analyst-facing release では HS2/HS4/HS6/HS8/HSK10 grain を分離して提供します。canonical HSK10 は厳密な numeric 10-digit source data のみを保持し、短い upstream code は隔離して padding や推測を行いません。residual-aware aggregation は、観測された prefix だけで推測なしに識別できる hierarchy level に限り exception を組み込めます。

## Dataset positioning

対象 Kaggle dataset:

**South Korea Customs Trade 2012–2026 — 10-Digit Product Level**

Positioning statement:

> South Korea's monthly customs trade at the full 10-digit HSK product level, across 200+ partner economies, with HS6/HS4/HS2 mappings and long-term history.
