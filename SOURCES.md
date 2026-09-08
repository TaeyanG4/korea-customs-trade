# Sources and provenance

## Primary trade facts

**Korea Customs Service — 품목별 국가별 수출입실적(GW)**  
Korea Public Data Portal (`data.go.kr`)  
Dataset page: https://www.data.go.kr/data/15100475/openapi.do  
Endpoint: https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList

The official description states that the data are compiled from customs clearance records and reports imports on a CIF/customs-value basis, exports on an FOB basis, net weight in kilograms, and monthly revisions reflecting declaration corrections/withdrawals.

The public-data listing describes the reuse scope as **이용허락범위 제한 없음** (no restriction on scope of use). Kaggle metadata therefore uses `Other` rather than inventing a Creative Commons license that the source does not state.

## Historical HSK reference

**Korea Customs Service CLIP — Korean annual tariff tables**  
https://unipass.customs.go.kr/clip/index.do

Annual 2012–2026 Korean tariff-table editions are used to build `hsk_code_reference.parquet`, including Korean and English names and the HS hierarchy prefixes.

## Country-code reference

The KCS lookup workbook (`관세청조회코드`) distributed with the Korea Customs public API documentation is authoritative for collection codes and Korean names.

## English country enrichment

**United Nations Statistics Division — M49 Standard**  
https://unstats.un.org/unsd/methodology/m49/

UN fields are added only for exact current alpha-2 matches. KCS-specific or historical codes remain in the dataset without guessed English metadata.

## Transformation statement

This Kaggle release is a reproducible repackaging and analytical derivation of official public data. The project does not claim authorship of the underlying government statistics. Source exceptions are retained and documented rather than cosmetically rewritten.
