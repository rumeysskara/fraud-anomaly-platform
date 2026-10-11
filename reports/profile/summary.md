# Profil ozeti

Satir: 590540, kolon (has_identity dahil): 433

## Join
- transaction_rows: 590540
- identity_rows_in_file: 144233
- identity_rows_in_scope: 144233
- duplicate_transaction_ids: 0
- duplicate_identity_ids: 0
- rows_after_join: 590540
- matched_rows: 144233

## Tip dagilimi
| type | n |
|---|---|
| numeric | 301 |
| categorical | 105 |
| flag | 26 |
| id | 1 |
| datetime | 1 |


## Yuksek cardinality
| column | inferred_type | n_unique | null_ratio |
|---|---|---|---|
| TransactionID | id | 590540 | 0 |
| card1 | categorical | 13553 | 0 |
| DeviceInfo | categorical | 1786 | 0.7991 |


## Grup bazli eksik veri
| group | n_columns | mean_null_ratio | min_null_ratio | max_null_ratio | n_cols_over_threshold | n_null_blocks |
|---|---|---|---|---|---|---|
| V | 339 | 0.4304 | 2.032e-05 | 0.8612 | 0 | 15 |
| id | 38 | 0.8482 | 0.7558 | 0.992 | 10 | 25 |
| D | 15 | 0.5815 | 0.002149 | 0.9341 | 1 | 14 |
| C | 14 | 0 | 0 | 0 | 0 | 1 |
| M | 9 | 0.4992 | 0.2868 | 0.5935 | 0 | 6 |
| other | 8 | 0.311 | 0 | 0.7991 | 0 | 5 |
| card | 6 | 0.005053 | 0 | 0.01513 | 0 | 6 |
| addr | 2 | 0.1113 | 0.1113 | 0.1113 | 0 | 1 |
| dist | 2 | 0.7664 | 0.5965 | 0.9363 | 1 | 2 |


## Kalite bulgulari
| check | column | value |
|---|---|---|
| high_null_column | dist2 | 0.9363 |
| high_null_column | D7 | 0.9341 |
| high_null_column | id_07 | 0.9913 |
| high_null_column | id_08 | 0.9913 |
| high_null_column | id_18 | 0.9236 |
| high_null_column | id_21 | 0.9913 |
| high_null_column | id_22 | 0.9912 |
| high_null_column | id_23 | 0.9912 |
| high_null_column | id_24 | 0.992 |
| high_null_column | id_25 | 0.9913 |
| high_null_column | id_26 | 0.9913 |
| high_null_column | id_27 | 0.9912 |
| duplicate_rows | * | 3 |
| duplicate_index | * | 0 |
| negative_value | D4 | 15 |
| negative_value | D6 | 3 |
| negative_value | D11 | 7 |
| negative_value | D12 | 2 |
| negative_value | D14 | 3 |
| negative_value | D15 | 15 |
| non_positive_amount | TransactionAmt | 0 |


## Entity adaylari
| candidate | scope | undefined_ratio | n_entities | single_txn_entity_ratio | single_txn_row_share | txn_median | txn_p90 | txn_p99 | txn_max | repeat_row_share | holdout_seen_ratio |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A_card1 | full | 0 | 13553 | 0.2541 | 0.005832 | 4 | 46 | 786.4 | 14932 | 0.977 | 0.9891 |
| A_card1 | fit | 0 | 12730 | 0.2655 | 0.007154 | 4 | 39 | 678.3 | 12205 | 0.9731 | nan |
| B_card1_addr1 | full | 0.1113 | 37531 | 0.3948 | 0.02823 | 2 | 23 | 194 | 5885 | 0.9285 | 0.9569 |
| B_card1_addr1 | fit | 0.1138 | 34399 | 0.405 | 0.03328 | 2 | 20 | 169 | 4721 | 0.9178 | nan |
| C_card1_card2_card3_card5_addr1 | full | 0.1285 | 38145 | 0.3942 | 0.02922 | 2 | 22 | 187.6 | 5866 | 0.9259 | 0.9561 |
| C_card1_card2_card3_card5_addr1 | fit | 0.1311 | 35012 | 0.4056 | 0.0346 | 2 | 19 | 160 | 4708 | 0.9147 | nan |
| D_card_all_no_addr | full | 0.0187 | 13691 | 0.2545 | 0.006014 | 4 | 45 | 728.2 | 14112 | 0.9764 | 0.9891 |
| D_card_all_no_addr | fit | 0.01875 | 12867 | 0.2663 | 0.007393 | 4 | 38 | 633 | 11109 | 0.9722 | nan |
| E_card1_addr1_Pemail | full | 0.2673 | 73407 | 0.4973 | 0.08436 | 2 | 10 | 69 | 2242 | 0.8303 | 0.8723 |
| E_card1_addr1_Pemail | fit | 0.2649 | 65683 | 0.5096 | 0.09639 | 1 | 9 | 60 | 1791 | 0.8109 | nan |
| F_card1_addr1_DeviceInfo | full | 0.8675 | 31576 | 0.6657 | 0.2687 | 1 | 4 | 23 | 1309 | 0.5964 | 0.6628 |
| F_card1_addr1_DeviceInfo | fit | 0.8582 | 28645 | 0.6729 | 0.2877 | 1 | 4 | 22 | 198 | 0.5724 | nan |
| G_card1_Pemail | full | 0.1599 | 38162 | 0.4147 | 0.0319 | 2 | 17 | 187.4 | 7041 | 0.9231 | 0.9474 |
| G_card1_Pemail | fit | 0.1558 | 34664 | 0.4266 | 0.03707 | 2 | 15 | 167 | 5795 | 0.9131 | nan |
| H_card1_addr1_na_level | full | 0 | 39974 | 0.3941 | 0.02667 | 2 | 22 | 201.3 | 9928 | 0.9323 | 0.9578 |
| H_card1_addr1_na_level | fit | 0 | 36593 | 0.4044 | 0.03133 | 2 | 20 | 177 | 8088 | 0.9225 | nan |
| I_card1_addr1_D1n | full | 0 | 217850 | 0.5748 | 0.212 | 1 | 6 | 20 | 1414 | 0.6311 | 0.435 |
| I_card1_addr1_D1n | fit | 0 | 182535 | 0.5816 | 0.2247 | 1 | 5 | 19 | 361 | 0.6136 | nan |
| J_card1_addr1_Pemail_D1n | full | 0 | 273919 | 0.648 | 0.3006 | 1 | 4 | 15 | 1414 | 0.5362 | 0.3989 |
| J_card1_addr1_Pemail_D1n | fit | 0 | 229158 | 0.6586 | 0.3195 | 1 | 4 | 14 | 321 | 0.5149 | nan |


## D1n sabitlik kontrolu
| entity_level | scope | d1n_group | n_entities | entity_share | n_txn | txn_share | median_range_days |
|---|---|---|---|---|---|---|---|
| H_card1_addr1_na_level | all | single | 21476 | 0.5379 | 38371 | 0.06512 | 0 |
| H_card1_addr1_na_level | all | jitter | 99 | 0.00248 | 278 | 0.0004718 | 1 |
| H_card1_addr1_na_level | all | multi | 18348 | 0.4596 | 550622 | 0.9344 | 161 |
| H_card1_addr1_na_level | multi_txn | single | 5739 | 0.2373 | 22634 | 0.03946 | 0 |
| H_card1_addr1_na_level | multi_txn | jitter | 99 | 0.004093 | 278 | 0.0004847 | 1 |
| H_card1_addr1_na_level | multi_txn | multi | 18348 | 0.7586 | 550622 | 0.9601 | 161 |
| REF_card_full_addr1 | all | single | 23523 | 0.5475 | 41059 | 0.06968 | 0 |
| REF_card_full_addr1 | all | jitter | 112 | 0.002607 | 313 | 0.0005312 | 1 |
| REF_card_full_addr1 | all | multi | 19331 | 0.4499 | 547899 | 0.9298 | 160 |
| REF_card_full_addr1 | multi_txn | single | 6176 | 0.2411 | 23712 | 0.04146 | 0 |
| REF_card_full_addr1 | multi_txn | jitter | 112 | 0.004372 | 313 | 0.0005473 | 1 |
| REF_card_full_addr1 | multi_txn | multi | 19331 | 0.7546 | 547899 | 0.958 | 160 |
| I_card1_addr1_D1n | all | single | 217020 | 1 | 589271 | 1 | 0 |
| I_card1_addr1_D1n | all | jitter | 0 | 0 | 0 | 0 | nan |
| I_card1_addr1_D1n | all | multi | 0 | 0 | 0 | 0 | nan |
| I_card1_addr1_D1n | multi_txn | single | 92431 | 1 | 464682 | 1 | 0 |
| I_card1_addr1_D1n | multi_txn | jitter | 0 | 0 | 0 | 0 | nan |
| I_card1_addr1_D1n | multi_txn | multi | 0 | 0 | 0 | 0 | nan |

