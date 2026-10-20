# Research run 1 (S0): feasibility counts, all 48 grid points

Source: the `feasibility` lines of the verification rerun reports (`16-46-run1-<family>-rerun-report.txt`), copied without interpretation. Reporting only: no verdict, ranking or selection. Floors as printed: pooled 100 closed trades, 30 per fold. Pooled = the four Validation folds together. `end_of_data` = trades closed by end of data; `settlement` = Development settlement count (when printed).

## trend-pullback

| point | dev closed | dev end_of_data | dev settlement | pooled closed (floor) | fold closed (floor 30) | end_of_data pooled | end_of_data by fold | shortfalls |
|---|---|---|---|---|---|---|---|---|
| a01 | 570 | 2 | 1 | 343 (100) | 102,95,71,75 | 1 | 1,0,0,0 | - |
| a02 | 513 | 2 | 1 | 330 (100) | 90,91,73,76 | 1 | 1,0,0,0 | - |
| a03 | 364 | 2 | 1 | 228 (100) | 60,73,50,45 | 1 | 0,1,0,0 | - |
| a04 | 343 | 2 | 1 | 240 (100) | 69,68,53,50 | 1 | 0,1,0,0 | - |
| a05 | 290 | 2 | - | 195 (100) | 44,60,39,52 | 2 | 0,0,0,2 | - |
| a06 | 294 | 2 | - | 191 (100) | 58,51,29,53 | 3 | 0,0,1,2 | fold 3: 29 closed trades, floor 30 |
| a07 | 194 | 2 | - | 122 (100) | 32,41,27,22 | 3 | 0,1,0,2 | fold 3: 27 closed trades, floor 30; fold 4: 22 closed trades, floor 30 |
| a08 | 192 | 2 | - | 118 (100) | 38,43,8,29 | 5 | 0,2,2,1 | fold 3: 8 closed trades, floor 30; fold 4: 29 closed trades, floor 30 |
| a09 | 477 | 2 | 1 | 296 (100) | 77,87,68,64 | 3 | 1,0,0,2 | - |
| a10 | 442 | 2 | 1 | 305 (100) | 76,89,68,72 | 3 | 1,0,0,2 | - |
| a11 | 340 | 2 | 1 | 218 (100) | 50,60,54,54 | 3 | 1,0,0,2 | - |
| a12 | 308 | 2 | 1 | 217 (100) | 52,60,52,53 | 3 | 1,0,0,2 | - |
| a13 | 304 | 2 | - | 200 (100) | 56,58,31,55 | 5 | 1,1,1,2 | - |
| a14 | 284 | 2 | 1 | 196 (100) | 54,59,29,54 | 5 | 1,1,1,2 | fold 3: 29 closed trades, floor 30 |
| a15 | 184 | 2 | - | 139 (100) | 33,43,24,39 | 6 | 1,2,1,2 | fold 3: 24 closed trades, floor 30 |
| a16 | 171 | 2 | 1 | 133 (100) | 30,42,22,39 | 6 | 1,2,1,2 | fold 3: 22 closed trades, floor 30 |

Points: 16; points with at least one printed shortfall line: 6.

## breakout-retest

| point | dev closed | dev end_of_data | dev settlement | pooled closed (floor) | fold closed (floor 30) | end_of_data pooled | end_of_data by fold | shortfalls |
|---|---|---|---|---|---|---|---|---|
| b01 | 234 | 0 | - | 145 (100) | 38,41,28,38 | 5 | 1,2,1,1 | fold 3: 28 closed trades, floor 30 |
| b02 | 209 | 0 | - | 161 (100) | 45,44,34,38 | 4 | 1,2,0,1 | - |
| b03 | 142 | 1 | - | 98 (100) | 24,28,20,26 | 6 | 1,1,2,2 | pooled: 98 closed trades, floor 100; fold 1: 24 closed trades, floor 30; fold 2: 28 closed trades, floor 30; fold 3: 20 closed trades, floor 30; fold 4: 26 closed trades, floor 30 |
| b04 | 137 | 2 | - | 99 (100) | 18,33,21,27 | 4 | 1,1,1,1 | pooled: 99 closed trades, floor 100; fold 1: 18 closed trades, floor 30; fold 3: 21 closed trades, floor 30; fold 4: 27 closed trades, floor 30 |
| b05 | 258 | 1 | - | 140 (100) | 33,45,15,47 | 7 | 1,2,2,2 | fold 3: 15 closed trades, floor 30 |
| b06 | 236 | 1 | - | 150 (100) | 37,47,16,50 | 6 | 1,2,2,1 | fold 3: 16 closed trades, floor 30 |
| b07 | 153 | 2 | - | 99 (100) | 16,30,21,32 | 7 | 1,2,2,2 | pooled: 99 closed trades, floor 100; fold 1: 16 closed trades, floor 30; fold 3: 21 closed trades, floor 30 |
| b08 | 147 | 2 | - | 102 (100) | 16,38,22,26 | 4 | 1,2,1,0 | fold 1: 16 closed trades, floor 30; fold 3: 22 closed trades, floor 30; fold 4: 26 closed trades, floor 30 |
| b09 | 264 | 0 | - | 165 (100) | 44,43,30,48 | 6 | 1,2,1,2 | - |
| b10 | 226 | 0 | - | 162 (100) | 47,28,39,48 | 4 | 1,2,0,1 | fold 2: 28 closed trades, floor 30 |
| b11 | 144 | 2 | - | 95 (100) | 16,28,22,29 | 8 | 2,2,2,2 | pooled: 95 closed trades, floor 100; fold 1: 16 closed trades, floor 30; fold 2: 28 closed trades, floor 30; fold 3: 22 closed trades, floor 30; fold 4: 29 closed trades, floor 30 |
| b12 | 129 | 1 | - | 102 (100) | 18,33,25,26 | 4 | 1,1,1,1 | fold 1: 18 closed trades, floor 30; fold 3: 25 closed trades, floor 30; fold 4: 26 closed trades, floor 30 |
| b13 | 253 | 0 | - | 132 (100) | 36,34,18,44 | 6 | 1,2,2,1 | fold 3: 18 closed trades, floor 30 |
| b14 | 257 | 0 | - | 150 (100) | 38,36,32,44 | 4 | 1,2,1,0 | - |
| b15 | 149 | 1 | - | 107 (100) | 16,30,27,34 | 7 | 1,2,2,2 | fold 1: 16 closed trades, floor 30; fold 3: 27 closed trades, floor 30 |
| b16 | 144 | 2 | - | 107 (100) | 17,39,23,28 | 6 | 1,2,1,2 | fold 1: 17 closed trades, floor 30; fold 3: 23 closed trades, floor 30; fold 4: 28 closed trades, floor 30 |

Points: 16; points with at least one printed shortfall line: 13.

## range-mr

| point | dev closed | dev end_of_data | dev settlement | pooled closed (floor) | fold closed (floor 30) | end_of_data pooled | end_of_data by fold | shortfalls |
|---|---|---|---|---|---|---|---|---|
| c01 | 300 | 0 | 1 | 161 (100) | 44,40,40,37 | 1 | 0,0,0,1 | - |
| c02 | 317 | 0 | 1 | 167 (100) | 46,43,41,37 | 1 | 0,0,0,1 | - |
| c03 | 300 | 0 | 1 | 163 (100) | 44,40,42,37 | 1 | 0,0,0,1 | - |
| c04 | 318 | 0 | 1 | 167 (100) | 46,43,41,37 | 1 | 0,0,0,1 | - |
| c05 | 290 | 0 | 1 | 161 (100) | 45,40,39,37 | 1 | 0,0,0,1 | - |
| c06 | 300 | 0 | 1 | 168 (100) | 48,43,40,37 | 1 | 0,0,0,1 | - |
| c07 | 292 | 0 | 1 | 163 (100) | 45,40,41,37 | 1 | 0,0,0,1 | - |
| c08 | 301 | 0 | 1 | 168 (100) | 48,43,40,37 | 1 | 0,0,0,1 | - |
| c09 | 300 | 0 | 1 | 161 (100) | 44,40,40,37 | 1 | 0,0,0,1 | - |
| c10 | 317 | 0 | 1 | 167 (100) | 46,43,41,37 | 1 | 0,0,0,1 | - |
| c11 | 300 | 0 | 1 | 163 (100) | 44,40,42,37 | 1 | 0,0,0,1 | - |
| c12 | 318 | 0 | 1 | 167 (100) | 46,43,41,37 | 1 | 0,0,0,1 | - |
| c13 | 290 | 0 | 1 | 161 (100) | 45,40,39,37 | 1 | 0,0,0,1 | - |
| c14 | 300 | 0 | 1 | 168 (100) | 48,43,40,37 | 1 | 0,0,0,1 | - |
| c15 | 292 | 0 | 1 | 163 (100) | 45,40,41,37 | 1 | 0,0,0,1 | - |
| c16 | 301 | 0 | 1 | 168 (100) | 48,43,40,37 | 1 | 0,0,0,1 | - |

Points: 16; points with at least one printed shortfall line: 0.

Superseded (16-DEC-RUN1-SUPERSEDED.md, D076):
The original 240 records are retained unchanged as immutable historical evidence under the simulator semantics and protocol versions recorded in those records. They are superseded for the current confirmatory evaluation by the regenerated records produced under simulator_semantics_version 2.3.0 and protocol v2.6.0. The original records must not be pooled with the regenerated records, combined into their digests, or used as if both sets were produced under the same protocol and simulator semantics. The original artifacts and hashes remain available for historical audit and reproduction of the original run.
No experiment record was ever written under simulator_semantics_version 2.2.0 or protocol v2.5.0; the 2.2.0 rerun stopped at its first family with 0 records (evidence/16-61-run-output.txt).
