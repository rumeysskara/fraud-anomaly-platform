# D1 semantigi testi

| metric | value | n_rows | note |
|---|---|---|---|
| A_prev_gap_matches_D1 | 0.3444 | 549367 | |gap to previous txn in entity (days) - D1| <= 1; rows without a previous txn excluded |
| A_prev_gap_matches_D1_permuted | 0.3336 | 549367 | same, with D1 shuffled inside the entity (chance level) |
| B_pair_seen_before[all_D1_rows] | 0.6317 | 589271 | (entity, D1n) pair seen in an earlier row |
| B_pair_seen_before_permuted[all_D1_rows] | 0.3300 | 589271 | same, D1 shuffled inside the entity (seed 42) |
| B_pair_seen_before[rows_with_previous_txn] | 0.6776 | 549367 | (entity, D1n) pair seen in an earlier row |
| B_pair_seen_before_permuted[rows_with_previous_txn] | 0.3540 | 549367 | same, D1 shuffled inside the entity (seed 42) |
