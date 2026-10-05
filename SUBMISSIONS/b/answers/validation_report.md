# Validation report

| form | fields | answer | not_applicable | missing_information | bank_reserved | human_action | downgraded | warnings | requests | prompt tok | completion tok (reasoning) | seconds |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| form_01 | 23 | 20 | 1 | 1 | 0 | 1 | 0 | 0 | 1 | 8032 | 9883 (6390) | 257 |
| form_02 | 27 | 18 | 7 | 0 | 1 | 1 | 0 | 0 | 1 | 10668 | 8289 (4928) | 138 |
| form_03 | 80 | 37 | 41 | 1 | 0 | 1 | 0 | 0 | 2 | 21919 | 14319 (4425) | 178 |
| form_04 | 35 | 19 | 13 | 0 | 3 | 0 | 0 | 0 | 1 | 12972 | 13362 (7082) | 114 |
| form_05 | 71 | 38 | 33 | 0 | 0 | 0 | 0 | 0 | 3 | 38252 | 26329 (13453) | 248 |

## form_04: downgraded / warnings / unanswered

- p3 Crimea: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p4 Cuba: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p4 Iran: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p4 North Korea: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p4 Sudan: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p4 Syria: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p4 Zaporizhzhia: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p4 Kherson: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p4 Donetsk: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p4 Luhansk: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**

## form_05: downgraded / warnings / unanswered

- p8 Iran / Iran: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p8 Korea Północna / North Korea: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p8 Syria / Syria: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p8 Białoruś / Belarus: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p8 Rosja / Russia: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p8 Krym / Crimea: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p8 Wenezuela (rząd Wenezueli lub wenezuelski sektor energetyczny lub złot: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p9 Niekontrolowane przez rząd Ukrainy obszary obwodu donieckiego / Non-go: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p9 Niekontrolowane przez rząd Ukrainy obszary obwodu ługańskiego / Non-go: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p9 Niekontrolowane przez rząd Ukrainy obszary obwodu chersońskiego / Non-: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p9 Niekontrolowane przez rząd Ukrainy obszary obwodu zaporoskiego / Non-g: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p10 Afganistan / Afghanistan: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p10 Angola / Angola: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p10 Białoruś / Belarus: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p10 Republika Środkowoafrykańska / Central African Republic: **state fixed: only zero/placeholder rows -> not_applicable (left blank)**
- p10 Korea Północna / North Korea: **state fixed: answer without value -> not_applicable**
- p10 Demokratyczna Republika Kongo / Democratic Republic of Congo: **state fixed: answer without value -> not_applicable**
- p10 Haiti / Haiti: **state fixed: answer without value -> not_applicable**
- p10 Iran / Iran: **state fixed: answer without value -> not_applicable**
- p10 Irak / Iraq: **state fixed: answer without value -> not_applicable**
- p10 Wybrzeże Kości Słoniowej / Ivory Coast: **state fixed: answer without value -> not_applicable**
- p10 Liberia / Liberia: **state fixed: answer without value -> not_applicable**
- p10 Libia / Libya: **state fixed: answer without value -> not_applicable**
- p10 Rosja / Russia: **state fixed: answer without value -> not_applicable**
- p10 Sierra Leone / Sierra Leone: **state fixed: answer without value -> not_applicable**
- p10 Somalia / Somalia: **state fixed: answer without value -> not_applicable**
- p11 Sudan Południowy / South Sudan: **state fixed: answer without value -> not_applicable**
- p11 Sudan / Sudan: **state fixed: answer without value -> not_applicable**
- p11 Syria / Syria: **state fixed: answer without value -> not_applicable**
- p11 Wenezuela / Venezuela: **state fixed: answer without value -> not_applicable**
- p11 Jemen / Yemen: **state fixed: answer without value -> not_applicable**
- p11 Zimbabwe / Zimbabwe: **state fixed: answer without value -> not_applicable**

## Every paid request (including failed ones)

| raw file | provider | finish | prompt tok | completion tok | reasoning tok | seconds |
|---|---|---|---|---|---|---|
| form_01_S1_try1.json | ModelRun | stop | 8032 | 9883 | 6390 | 256.6 |
| form_02_S1_try1.json | ModelRun | error | 9094 | 15357 | 15357 | 332.6 |
| form_02_S1_try2.json | ModelRun | stop | 10668 | 8289 | 4928 | 138.1 |
| form_03_S1_try1.json | ModelRun | stop | 9844 | 4672 | 2477 | 74.9 |
| form_03_S2_try1.json | ModelRun | stop | 12075 | 9647 | 1948 | 102.9 |
| form_04_S1_try1.json | ModelRun | stop | 12972 | 13362 | 7082 | 114.5 |
| form_05_S1_try1.json | ModelRun | stop | 13634 | 11174 | 5443 | 108.5 |
| form_05_S2_rest_try1.json | ModelRun | stop | 11849 | 7506 | 3408 | 71.8 |
| form_05_S2_try1.json | ModelRun | error | 12769 | 7649 | 4602 | 67.5 |
