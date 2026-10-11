# Research execution

- Respect the user's standing request to continue authorized work until a real blocker or decision. A progress update, completed stage or routine checkpoint is not a reason to ask again or finish the turn.
- At recovery, confirm remote commit and input hashes. Scratch files may be absent or old. Restore frozen inputs from saved checkpoints; never substitute a different dataset silently.
- Use `research_pipeline.py` for multi-stage jobs. Hash-verified stage outputs are the only basis for skipping work. Run heavy stages serially; don't start duplicate workers. Source acquisition uses two workers and its own file lock.
- Keep meaningful user updates within 60 seconds during active work. Heartbeats show liveness, not proof of productive progress.
- Package and save raw sources before expensive downstream research. Save the archive, retrieve it, verify SHA/CRC/manifest, then write a receipt. An `awaiting_checkpoint` exit is an agent save/restore step within authorized work, not a new user approval request.
- Commit small reports, Tasks and checkpoint receipts after milestones. Local state and logs alone are not durable. Never commit raw large datasets.
- Record actual transport errors and resource observations. Do not infer OOM, source blocking, session quotas or platform root cause from silence.
- Never promise continued execution after a final response or automatic recovery from whole-environment loss. A runner in that environment cannot restart itself after the environment disappears.
- Keep current model/rule parameters frozen. No trading or person-directed messages are authorized by research execution.
