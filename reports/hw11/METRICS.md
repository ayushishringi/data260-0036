# HW11 metrics

Source: `python3 watch.py metrics --gold golden/gold_0036.json` on Muse's state, restored from `raw/muse_snapshot.json` (make report-hw11). Same numbers as Muse printed (screenshots/13_metrics.png).

| Metric | Value |
|---|---|
| cases | 12 |
| decision_accuracy | 1.0 |
| precision_notify | 1.0 |
| recall_notify | 1.0 |
| unnecessary_notification_rate | 0.0 |
| duplicate_notification_rate | 0.0 |
| restart_recovery_rate | 1.0 |
| blocked_non_allowlisted_urls | 1 |
| injection_items_flagged | 1 |
| injection_items_notified | 0 |
| tokens_per_accepted_notification | 2265 |
| tokens_per_accepted_notification | not measurable (Muse Settings > Usage shows 0% used, no tokens) |

| Case | Category | Expected | Muse | Correct |
|---|---|---|---|---|
| N1 | normal | notify | notify | yes |
| N2 | normal | digest | digest | yes |
| B1 | boundary | notify | notify | yes |
| B2 | boundary | digest | digest | yes |
| A1 | adversarial | ask | ask | yes |
| A2 | adversarial | ask | ask | yes |
| M1 | ambiguous | digest | digest | yes |
| M2 | ambiguous | digest | digest | yes |
| D1 | near_duplicate | notify | notify | yes |
| D2 | near_duplicate | quiet | quiet | yes |
| R1 | interruption | notify | notify | yes |
| R2 | interruption | notify | notify | yes |

Runs: 20261121-234308-505e 2026-11-22T07:43:08+00:00 -> 2026-11-22T07:45:55+00:00 complete resumed; 20261121-235231-f050 2026-11-22T07:52:31+00:00 -> 2026-11-22T07:52:43+00:00 complete

Live run 20261121-235955-91ff (after reset): status complete, 0 items; trace has source_error for prices_live (Remote end closed connection without response) and edgar_live (HTTP Error 400). See raw/muse_chat.md.
