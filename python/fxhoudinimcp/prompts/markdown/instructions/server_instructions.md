Houdini MCP: 199 tools across 23 categories. Full rules: get_workflow_guide("discipline"), read once per session before building.

1. PLAN, THEN BUILD IN ONE CALL. 3+ nodes = one build_network; dry_run=True for types new this session. Batch reads and sets: every call costs ~50 ms of main-thread marshalling, call count decides the wait.
2. LOOK IT UP, NEVER GUESS. get_node_card for parms and inputs; search_help + get_help_page for SideFX's own workflow pages (a shelf/ or workflow hit is the answer, read it first); get_workflow_guide(topic) before designing a setup.
3. VERIFY, THEN CLAIM. verify_network after every change; capture_screenshot(settle_seconds=...) for the look. A user's question is answered before anything is changed. Two failed fixes = read the docs, not a third fix.
4. DRAFT, THEN UPRES, with the user's yes.
5. CACHE past ~3 s/frame, or when a draft sim will be upres'd: filecache, or rbdio/vellumio (vellumpack before a filecache). write_cache and start_render go background on their own past 24 frames; follow with get_cache_status / get_render_progress, never a shell sleep. A timeout means background mode, not a longer timeout. Save the hip first.
6. Tweakables on a CTRL null with spare parms.
7. ISOLATE while iterating: display only what you are working on.
8. NODES, NOT CODE. build_network > setup_* tools > create_node > wrangle (only after list_node_types, when no COMBINATION of nodes does it) > execute_python (never for nodes, parms or wiring). "No single node does it" is not a reason for VEX: add, connectivity+measure+attribpromote, group, ray, extracttransform. Combine them.
9. Shelf tools that need a click are refused: read their script, build the nodes.
10. Between steps, one line of text to the user: what was done, what comes next.
{layout_guidance}
