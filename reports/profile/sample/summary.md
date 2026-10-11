# Profil ozeti

Satir: 50000, kolon (has_identity dahil): 433

## Join
- transaction_rows: 50000
- identity_rows_in_file: 144233
- identity_rows_in_scope: 16456
- duplicate_transaction_ids: 0
- duplicate_identity_ids: 0
- rows_after_join: 50000
- matched_rows: 16456

## Tip dagilimi
| type | n |
|---|---|
| numeric | 247 |
| categorical | 153 |
| flag | 31 |
| id | 2 |
| datetime | 1 |


## Yuksek cardinality
| column | inferred_type | n_unique | null_ratio |
|---|---|---|---|
| TransactionID | id | 50000 | 0 |
| card1 | categorical | 5446 | 0 |
| id_02 | id | 15545 | 0.6786 |


## Grup bazli eksik veri
| group | n_columns | mean_null_ratio | min_null_ratio | max_null_ratio | n_cols_over_threshold | n_null_blocks |
|---|---|---|---|---|---|---|
| V | 339 | 0.4327 | 0 | 0.7557 | 0 | 12 |
| id | 38 | 0.789 | 0.6709 | 0.9888 | 10 | 22 |
| D | 15 | 0.6453 | 0 | 0.9529 | 5 | 14 |
| C | 14 | 0 | 0 | 0 | 0 | 1 |
| M | 9 | 0.6591 | 0.3734 | 0.8155 | 0 | 5 |
| other | 8 | 0.2923 | 0 | 0.7668 | 0 | 5 |
| card | 6 | 0.003147 | 0 | 0.01394 | 0 | 5 |
| addr | 2 | 0.05182 | 0.05182 | 0.05182 | 0 | 1 |
| dist | 2 | 0.7976 | 0.6624 | 0.9329 | 1 | 2 |


## Kalite bulgulari
| check | column | value |
|---|---|---|
| high_null_column | dist2 | 0.9329 |
| high_null_column | D6 | 0.9035 |
| high_null_column | D7 | 0.9529 |
| high_null_column | D12 | 0.9181 |
| high_null_column | D13 | 0.9264 |
| high_null_column | D14 | 0.9134 |
| constant_column | M1 | 1 |
| constant_column | V107 | 1 |
| high_null_column | id_07 | 0.9879 |
| high_null_column | id_08 | 0.9879 |
| high_null_column | id_18 | 0.9029 |
| high_null_column | id_21 | 0.9879 |
| high_null_column | id_22 | 0.9878 |
| high_null_column | id_23 | 0.9878 |
| high_null_column | id_24 | 0.9888 |
| high_null_column | id_25 | 0.988 |
| high_null_column | id_26 | 0.9878 |
| high_null_column | id_27 | 0.9878 |
| duplicate_rows | * | 0 |
| duplicate_index | * | 0 |
| negative_value | D4 | 6 |
| negative_value | D6 | 1 |
| negative_value | D11 | 3 |
| negative_value | D12 | 1 |
| negative_value | D14 | 3 |
| negative_value | D15 | 7 |
| non_positive_amount | TransactionAmt | 0 |


## Entity adaylari
| candidate | scope | undefined_ratio | n_entities | single_txn_entity_ratio | single_txn_row_share | txn_median | txn_p90 | txn_p99 | txn_max | repeat_row_share | holdout_seen_ratio |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A_card1 | full | 0 | 5446 | 0.439 | 0.04782 | 2 | 13 | 145.7 | 1750 | 0.8911 | 0.9131 |
| A_card1 | fit | 0 | 4774 | 0.4623 | 0.05518 | 2 | 12 | 128.8 | 1632 | 0.8807 | nan |
| B_card1_addr1 | full | 0.05182 | 12107 | 0.5326 | 0.136 | 1 | 7 | 45.94 | 466 | 0.7446 | 0.7731 |
| B_card1_addr1 | fit | 0.05655 | 10314 | 0.5438 | 0.1486 | 1 | 6 | 41 | 378 | 0.7267 | nan |
| C_card1_card2_card3_card5_addr1 | full | 0.06914 | 12167 | 0.5394 | 0.141 | 1 | 7 | 44 | 466 | 0.7386 | 0.7696 |
| C_card1_card2_card3_card5_addr1 | fit | 0.07345 | 10377 | 0.5505 | 0.1541 | 1 | 6 | 39 | 378 | 0.72 | nan |
| D_card_all_no_addr | full | 0.01772 | 5460 | 0.4414 | 0.04907 | 2 | 12 | 142.8 | 1065 | 0.8888 | 0.9114 |
| D_card_all_no_addr | fit | 0.01725 | 4787 | 0.4646 | 0.05658 | 2 | 12 | 128 | 948 | 0.8782 | nan |
| E_card1_addr1_Pemail | full | 0.2284 | 17513 | 0.6657 | 0.3022 | 1 | 4 | 17 | 148 | 0.5461 | 0.5563 |
| E_card1_addr1_Pemail | fit | 0.2379 | 14455 | 0.6771 | 0.3211 | 1 | 4 | 16 | 121 | 0.5258 | nan |
| F_card1_addr1_DeviceInfo | full | 0.7419 | 7940 | 0.7519 | 0.4626 | 1 | 3 | 10 | 29 | 0.3848 | 0.3586 |
| F_card1_addr1_DeviceInfo | fit | 0.7661 | 6043 | 0.7627 | 0.4926 | 1 | 3 | 9 | 28 | 0.3541 | nan |
| G_card1_Pemail | full | 0.1797 | 10325 | 0.5885 | 0.1481 | 1 | 6 | 47 | 765 | 0.7483 | 0.7779 |
| G_card1_Pemail | fit | 0.1852 | 8771 | 0.601 | 0.1617 | 1 | 6 | 44 | 714 | 0.7309 | nan |
| H_card1_addr1_na_level | full | 0 | 12463 | 0.5309 | 0.1323 | 1 | 7 | 47 | 466 | 0.7507 | 0.7767 |
| H_card1_addr1_na_level | fit | 0 | 10638 | 0.5421 | 0.1442 | 1 | 7 | 42 | 378 | 0.734 | nan |
| I_card1_addr1_D1n | full | 0 | 31249 | 0.7272 | 0.4545 | 1 | 3 | 8 | 62 | 0.375 | 0.236 |
| I_card1_addr1_D1n | fit | 0 | 25569 | 0.7411 | 0.4738 | 1 | 3 | 8 | 62 | 0.3608 | nan |
| J_card1_addr1_Pemail_D1n | full | 0 | 36145 | 0.7949 | 0.5746 | 1 | 2 | 6 | 48 | 0.2771 | 0.1928 |
| J_card1_addr1_Pemail_D1n | fit | 0 | 29390 | 0.805 | 0.5915 | 1 | 2 | 6 | 47 | 0.2652 | nan |


## D1n sabitlik kontrolu
| entity_level | scope | d1n_group | n_entities | entity_share | n_txn | txn_share | median_range_days |
|---|---|---|---|---|---|---|---|
| H_card1_addr1_na_level | all | single | 8099 | 0.6498 | 10873 | 0.2175 | 0 |
| H_card1_addr1_na_level | all | jitter | 142 | 0.01139 | 340 | 0.0068 | 1 |
| H_card1_addr1_na_level | all | multi | 4222 | 0.3388 | 38787 | 0.7757 | 143 |
| H_card1_addr1_na_level | multi_txn | single | 1483 | 0.2536 | 4257 | 0.09812 | 0 |
| H_card1_addr1_na_level | multi_txn | jitter | 142 | 0.02429 | 340 | 0.007837 | 1 |
| H_card1_addr1_na_level | multi_txn | multi | 4222 | 0.7221 | 38787 | 0.894 | 143 |
| REF_card_full_addr1 | all | single | 8461 | 0.6563 | 11289 | 0.2258 | 0 |
| REF_card_full_addr1 | all | jitter | 146 | 0.01133 | 354 | 0.00708 | 1 |
| REF_card_full_addr1 | all | multi | 4284 | 0.3323 | 38357 | 0.7671 | 142 |
| REF_card_full_addr1 | multi_txn | single | 1529 | 0.2566 | 4357 | 0.1012 | 0 |
| REF_card_full_addr1 | multi_txn | jitter | 146 | 0.0245 | 354 | 0.00822 | 1 |
| REF_card_full_addr1 | multi_txn | multi | 4284 | 0.7189 | 38357 | 0.8906 | 142 |
| I_card1_addr1_D1n | all | single | 31249 | 1 | 50000 | 1 | 0 |
| I_card1_addr1_D1n | all | jitter | 0 | 0 | 0 | 0 | nan |
| I_card1_addr1_D1n | all | multi | 0 | 0 | 0 | 0 | nan |
| I_card1_addr1_D1n | multi_txn | single | 8524 | 1 | 27275 | 1 | 0 |
| I_card1_addr1_D1n | multi_txn | jitter | 0 | 0 | 0 | 0 | nan |
| I_card1_addr1_D1n | multi_txn | multi | 0 | 0 | 0 | 0 | nan |


## Etiket taban orani (yalnizca raporlama)
- fit_base_rate: 0.0282
- holdout_base_rate: 0.0228
