# A10c CI flags / Bug Fixing Assess → Fix → Test (2026-11-12)

Assess: GitHub Actions 43155449250 failed only the new metadata and safe
stdio smoke tests. All other source/GUI/security checks succeeded; 768
unittest tests otherwise passed. Fresh CI has both optional seven-tool
background-browser and background-native modules off by default. It
advertised 129 remote / 128 local tools, not 143/142 on owner's fully
enabled Mac. The assumptions in two NEW tests were wrong; the application
correctly respected opt-in flags.

Fix: Do not enable optional modules in runtime. The full inventory test
temporarily patches enabled() to True ONLY in in-memory FastMCP registration
to verify all 143 policy entries. The real stdio test validates exact
runtime-permitted sets core128 plus each independent seven-tool option,
rather than forcing all flags on. No handler/permission/schema change.

Test: New tests 6 PASSED +419 subtests on owner Mac. Exact GitHub-style clean
HOME environment with missing feature_flags.json: five unittest tests PASS
and real stdio MCP tools/list + safe system_info reports 128 tools PASS.
CI rerun remains an independent release gate. No M8ven outreach.
