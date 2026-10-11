# Step 7D — first expanded natural-issue batch

Frozen runtime main: `bd9478adcd628262c0e01ea7862f7fa4f799bdba`.
Frozen upstream Boltons SHA: `4e5faa3d7e4008d89e0d8bf1ea87b6d9a061a16d`.
Frozen DeerFlow: `c0895d295bba34f6e95188fca380f555dabed891`.

Two genuine public issues with independent host-owned failing regression baselines:
- [#551](https://github.com/mahmoud/boltons/issues/551) — key computation repeated; singleton key error not surfaced.
- [#524](https://github.com/mahmoud/boltons/issues/524) — byte unit promotion on rounding boundaries.

Cases and tests are fixed before any paid inference. Real Planner, Explorer,
Coder, Tester, bounded Repair; no pre-written patch or model mocks. Both
successes and failures are published through independent Actions artifacts.
Temporary paid exact-branch+marker workflow is removed after execution.
This survey is exploratory and has no statistically meaningful success rate.
