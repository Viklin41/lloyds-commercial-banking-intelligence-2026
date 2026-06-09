# Attrition baseline EDA

Source: `BasicCompanyDataAsOneFile-2026-06-01.csv`  |  snapshot date: 2026-06-01  |  rows: 5,698,274

Cross-sectional base rates from a single snapshot. Transitions (the actual
attrition events) require a second snapshot or the API.

## Headline

| metric | value |
| --- | --- |
| companies | 5698274.0 |
| dormant_rate | 0.1148 |
| distress_rate | 0.0924 |
| accounts_overdue_rate | 0.0755 |
| has_charge_rate | 0.1432 |
| satisfied_no_outstanding_rate | 0.0267 |

## By target sector

| sector | n | dormant_rate | distress_rate | overdue_rate | has_charge_rate |
| --- | --- | --- | --- | --- | --- |
| Other | 2462073.0 | 0.1278 | 0.1112 | 0.0963 | 0.1212 |
| Technology, legal & professional | 802235.0 | 0.122 | 0.0748 | 0.0581 | 0.0801 |
| Wholesale & retail | 721818.0 | 0.0994 | 0.1154 | 0.0829 | 0.1006 |
| Real estate | 623627.0 | 0.1085 | 0.041 | 0.0347 | 0.4259 |
| Fast growth & emerging | 381588.0 | 0.1102 | 0.0832 | 0.0604 | 0.051 |
| Manufacturing | 229777.0 | 0.1138 | 0.1026 | 0.0855 | 0.214 |
| Healthcare | 224936.0 | 0.0803 | 0.0731 | 0.0539 | 0.1145 |
| Public sector, education & charities | 209680.0 | 0.06 | 0.0467 | 0.0413 | 0.0416 |
| Agriculture | 42540.0 | 0.0776 | 0.0522 | 0.0446 | 0.2764 |

## By size band (account-category proxy)

| size_band | n | dormant_rate | distress_rate | overdue_rate | has_charge_rate |
| --- | --- | --- | --- | --- | --- |
| unknown | 2151955.0 | 0.3039 | 0.0859 | 0.0558 | 0.0515 |
| BB | 1854551.0 | 0.0 | 0.1083 | 0.0958 | 0.1089 |
| SME | 1570407.0 | 0.0 | 0.0839 | 0.0775 | 0.2711 |
| Large | 115055.0 | 0.0 | 0.0765 | 0.0939 | 0.6251 |
| Midcorp | 6306.0 | 0.0 | 0.0339 | 0.0484 | 0.8324 |

## By company age

| age_bucket | n | dormant_rate | distress_rate | overdue_rate | has_charge_rate |
| --- | --- | --- | --- | --- | --- |
| 5-10 | 1309036.0 | 0.1349 | 0.1551 | 0.1426 | 0.1293 |
| 10-20 | 1119974.0 | 0.1144 | 0.1039 | 0.0934 | 0.1765 |
| 1-3 | 1081292.0 | 0.1332 | 0.0858 | 0.0413 | 0.063 |
| <1 | 795878.0 | 0.0006 | 0.0133 | 0.0 | 0.0216 |
| 3-5 | 699085.0 | 0.1706 | 0.0692 | 0.0566 | 0.0964 |
| 20+ | 692972.0 | 0.1234 | 0.0797 | 0.0792 | 0.4274 |

## Sampling bias check (first 50k vs random 50k vs full)

Shows why the first-N-rows sample must not be used for attrition rates.

| metric | first_50k | random_50k | full |
| --- | --- | --- | --- |
| dormant_rate | 0.2627 | 0.1133 | 0.1148 |
| distress_rate | 0.0712 | 0.0915 | 0.0924 |
| midcorp_share | 0.0004 | 0.0011 | 0.0011 |