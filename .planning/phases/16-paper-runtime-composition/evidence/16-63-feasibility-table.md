# Research run 1 under simulator semantics 2.3.0: feasibility counts, all 48 grid points

RUN_COMMIT: 58a5374aea2d99aa59104ca8faa516fbfd680630
SIMULATOR_SEMANTICS_VERSION 2.3.0, protocol v2.6.0
Records: `docs/research/experiments/research-run-1-v2-3-0/` (240).
Limitation (owner): the first Development window starts cold because the dataset begins 2024-10-03T00:00:00Z, so its WARMUP_INSUFFICIENT count is not comparable with the warm Validation folds.
RR_TOO_LOW counts include plans refused for a non-positive TP2 (protocol v2.6.0, D075: the planner returns NO_TRADE with the existing reason RR_TOO_LOW when the stored TP2 is not above zero), so an RR_TOO_LOW count is not only plans whose reward-to-risk is below the floor.

Source: the `feasibility` lines of the verification rerun reports in `16-63-run-output.txt`, copied without interpretation. Counts only: nothing is selected, compared or judged here. Floors as printed: pooled 100 closed trades, 30 per fold. Pooled = the four Validation folds together. `end_of_data` = trades closed by end of data; `settlement` = Development settlement count (when printed).

## trend-pullback

| point | dev closed | dev end_of_data | dev settlement | pooled closed (floor) | fold closed (floor 30) | end_of_data pooled | end_of_data by fold | shortfalls |
|---|---|---|---|---|---|---|---|---|
| a01 | 570 | 2 | 1 | 613 (100) | 175,164,126,148 | 1 | 1,0,0,0 | - |
| a02 | 513 | 2 | 1 | 602 (100) | 163,156,134,149 | 1 | 1,0,0,0 | - |
| a03 | 364 | 2 | 1 | 430 (100) | 102,127,101,100 | 1 | 0,1,0,0 | - |
| a04 | 343 | 2 | 1 | 436 (100) | 114,122,100,100 | 1 | 0,1,0,0 | - |
| a05 | 290 | 2 | - | 354 (100) | 86,104,74,90 | 3 | 0,1,0,2 | - |
| a06 | 294 | 2 | - | 354 (100) | 96,99,65,94 | 4 | 0,1,1,2 | - |
| a07 | 194 | 2 | - | 243 (100) | 71,68,48,56 | 3 | 0,1,0,2 | - |
| a08 | 192 | 2 | - | 236 (100) | 75,67,33,61 | 5 | 0,2,2,1 | - |
| a09 | 477 | 2 | 1 | 509 (100) | 133,136,117,123 | 3 | 1,0,0,2 | - |
| a10 | 442 | 2 | 1 | 518 (100) | 130,144,111,133 | 3 | 1,0,0,2 | - |
| a11 | 340 | 2 | 1 | 407 (100) | 95,114,98,100 | 3 | 1,0,0,2 | - |
| a12 | 308 | 2 | 1 | 401 (100) | 93,113,95,100 | 3 | 1,0,0,2 | - |
| a13 | 304 | 2 | - | 354 (100) | 85,107,69,93 | 5 | 1,1,1,2 | - |
| a14 | 284 | 2 | 1 | 361 (100) | 89,111,67,94 | 5 | 1,1,1,2 | - |
| a15 | 184 | 2 | - | 236 (100) | 59,63,45,69 | 6 | 1,2,1,2 | - |
| a16 | 171 | 2 | 1 | 250 (100) | 57,72,47,74 | 6 | 1,2,1,2 | - |

Points: 16; points with at least one printed shortfall line: 0.

## breakout-retest

| point | dev closed | dev end_of_data | dev settlement | pooled closed (floor) | fold closed (floor 30) | end_of_data pooled | end_of_data by fold | shortfalls |
|---|---|---|---|---|---|---|---|---|
| b01 | 234 | 0 | - | 253 (100) | 76,62,61,54 | 5 | 1,2,1,1 | - |
| b02 | 209 | 0 | - | 247 (100) | 73,73,52,49 | 5 | 1,2,1,1 | - |
| b03 | 142 | 1 | - | 163 (100) | 44,43,42,34 | 6 | 1,1,2,2 | - |
| b04 | 137 | 2 | - | 147 (100) | 42,20,42,43 | 5 | 1,2,1,1 | fold 2: 20 closed trades, floor 30 |
| b05 | 258 | 1 | - | 277 (100) | 82,66,72,57 | 5 | 1,2,1,1 | - |
| b06 | 236 | 1 | - | 275 (100) | 79,73,70,53 | 4 | 1,2,1,0 | - |
| b07 | 153 | 2 | - | 161 (100) | 43,36,39,43 | 7 | 1,2,2,2 | - |
| b08 | 147 | 2 | - | 140 (100) | 38,19,41,42 | 5 | 1,2,1,1 | fold 2: 19 closed trades, floor 30 |
| b09 | 264 | 0 | - | 294 (100) | 77,74,75,68 | 5 | 1,2,0,2 | - |
| b10 | 226 | 0 | - | 273 (100) | 78,66,66,63 | 4 | 1,2,0,1 | - |
| b11 | 144 | 2 | - | 157 (100) | 36,44,41,36 | 8 | 2,2,2,2 | - |
| b12 | 129 | 1 | - | 159 (100) | 40,31,43,45 | 6 | 1,2,1,2 | - |
| b13 | 253 | 0 | - | 278 (100) | 80,67,71,60 | 5 | 1,2,1,1 | - |
| b14 | 257 | 0 | - | 283 (100) | 82,73,67,61 | 6 | 1,2,1,2 | - |
| b15 | 149 | 1 | - | 168 (100) | 38,41,49,40 | 7 | 1,2,2,2 | - |
| b16 | 144 | 2 | - | 149 (100) | 41,23,48,37 | 5 | 1,2,1,1 | fold 2: 23 closed trades, floor 30 |

Points: 16; points with at least one printed shortfall line: 3.

## range-mr

| point | dev closed | dev end_of_data | dev settlement | pooled closed (floor) | fold closed (floor 30) | end_of_data pooled | end_of_data by fold | shortfalls |
|---|---|---|---|---|---|---|---|---|
| c01 | 300 | 0 | 1 | 299 (100) | 80,79,65,75 | 1 | 0,0,0,1 | - |
| c02 | 317 | 0 | 1 | 320 (100) | 90,86,67,77 | 1 | 0,0,0,1 | - |
| c03 | 300 | 0 | 1 | 302 (100) | 81,79,67,75 | 1 | 0,0,0,1 | - |
| c04 | 318 | 0 | 1 | 320 (100) | 90,86,67,77 | 1 | 0,0,0,1 | - |
| c05 | 290 | 0 | 1 | 297 (100) | 83,79,61,74 | 1 | 0,0,0,1 | - |
| c06 | 300 | 0 | 1 | 312 (100) | 90,84,64,74 | 1 | 0,0,0,1 | - |
| c07 | 292 | 0 | 1 | 300 (100) | 84,79,63,74 | 1 | 0,0,0,1 | - |
| c08 | 301 | 0 | 1 | 314 (100) | 92,84,64,74 | 1 | 0,0,0,1 | - |
| c09 | 300 | 0 | 1 | 300 (100) | 81,79,65,75 | 1 | 0,0,0,1 | - |
| c10 | 317 | 0 | 1 | 320 (100) | 90,86,67,77 | 1 | 0,0,0,1 | - |
| c11 | 300 | 0 | 1 | 302 (100) | 81,79,67,75 | 1 | 0,0,0,1 | - |
| c12 | 318 | 0 | 1 | 320 (100) | 90,86,67,77 | 1 | 0,0,0,1 | - |
| c13 | 290 | 0 | 1 | 296 (100) | 82,79,61,74 | 1 | 0,0,0,1 | - |
| c14 | 300 | 0 | 1 | 312 (100) | 90,84,64,74 | 1 | 0,0,0,1 | - |
| c15 | 292 | 0 | 1 | 298 (100) | 82,79,63,74 | 1 | 0,0,0,1 | - |
| c16 | 301 | 0 | 1 | 314 (100) | 92,84,64,74 | 1 | 0,0,0,1 | - |

Points: 16; points with at least one printed shortfall line: 0.

