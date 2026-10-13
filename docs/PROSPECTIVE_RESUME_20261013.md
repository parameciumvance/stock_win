# Prospective TPEx continuation, 2026-10-13

Remote main after seven-rule selection work: 74c298b1f9b1afda0f16115c3dbdd8038d53eadb.

- The five reviewed files were committed earlier at 89a19e1ea44ebc21646936ecb8e579708c0ba41e. Source preflight receipt at docs/PROSPECTIVE_PREFLIGHT_20261013.md and raw two-source archive in Library libfile_4dd61ce503d88191acb2cfb741fc11b4.
- Seven-method same-pool selection implementation: prospective_selection.py. Deterministic tie order by code; all three event rules, intersection, volatility, ATR and momentum use common as-of complete feature pool. Incomplete pool stays explicit; future target/return columns are refused.
- prospective_journal.py now refuses a complete signal until a raw replay gate and manifest digest are supplied. The selector labels its output derived_matrix_raw_replay_pending; it cannot independently upgrade to a live signal.
- 29 focused selection, journal and existing event/price tests pass.

## Recovery blocker

Complete historical warmup and source data reside in tpex_long_event_research_checkpoint.zip, Library ID libfile_5d60caa5ff548191974c07ece232ec74 (169,657,594 bytes). The local copy is absent. The prescribed Library download helper returned hosted apps tools/list request failed: network on three attempts; no bytes were returned, no SHA/CRC or replays were claimed. The failure is specific to this transfer path in this run and does not establish a source website, OOM, or model-capacity cause. The two small direct public source probes were successful.

## Resume order

1. Confirm main and the eight frozen Git blob hashes recorded in configs/tpex_prospective_protocol.json. Confirm no existing source acquisition process or live signal service before starting another.
2. Restore the exact checkpoint by its Library identity when the transfer path recovers. Compare ZIP SHA-256 and each member to its saved receipt before extracting. Do not substitute fresh downloads for this historical version.
3. Rebuild and validate the warmup matrix from frozen raw inputs; retain original as-of pool, corporate-action masks and the fixed five-day institutional lag. Fetch and archive current quote, flow and revenue snapshots and verify independent market calendar and continuous 0050 benchmark.
4. Run prospective_selection.py with SHA-verified input, then independently replay its selections from archived raw sources. Mark raw_replay_verified and seal a complete signal only when its full manifest and source records are proven and it is before the next-market-day entry. Any missing or late input is a recorded missing day, not a backfilled prospective decision.
5. Earliest signal date is 2026-10-14 in Asia/Taipei. The calendar and live inputs must be actually checked before activation; there is no scheduled service or automatic recovery from environment loss.
