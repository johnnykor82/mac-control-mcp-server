# CB33 Watcher guard SPEC v1.0 — 2026-11-09
User approved 2026-11-09 extending CB33 P06R-03 to protect previously completed autonomous workers with confirmed notification delivery before resuming old project.
R1: With old autonomous.state=completed and delivered, ACKed notification, watcher.tasks=watching, poll_executor_tasks MUST NOT GET, POST, write or re-deliver the old executor. This holds when project is enabled.
R2: Do not alter legacy nonautonomous workers or unfinished/unacknowledged autonomous work; no general loss of supervisor follow-up tracking.
R3: Filter only rows with same project_id/task_id where autonomous completed and delivery state delivered and acknowledged_at not null. All identity checked; never infer from a different worker's delivery. No migrations.
R4: Test RED then GREEN: old row excluded from dry-run and actual poll and not changed; new watching task still eligible, unACKed or different task delivery does not skip.
R5: Previous BF33 worker-a/b completed+ACKed, worker-c/d uncertain, original DB/project remain preserved. No resends of uncertain work. Test 2 new unique no-tool workers only after owner service and backup verified, then pause original project.
R6: Stop on 429; snapshot and compare old row hashes before and after live test. If impossible to keep invariant, pause immediately, do not falsify completion.
R7: Full relevant tests, Converge, Git commit and reversible owner-only deploy, preserve release 749a748 and original plist, no jkmac.
