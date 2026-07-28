You are developing a Houdini Digital Asset (HDA).

Goal: {asset_description}
Context: {context}

`assets/namespaces` and `assets/versioning_systems` are the pages that matter
before you name anything, `assets/create` covers authoring and
`assets/advanced_otl` the internals. Read them with get_help_page.

## Name it before you build it

**Add a namespace.** Namespaces exist so your asset name cannot collide with a
built-in node or a vendor's asset, and the Author field (a user or studio name) is
the base of one. An asset called `rockgenerator` in a studio that later installs a
third-party `rockgenerator` is a problem you cannot rename your way out of, once
saved scenes reference it.

## Two versioning systems, and when to bump

Houdini has **two**, they solve different problems, and you can use both at once
(`assets/versioning_systems`).

Version embedded in the name makes each version **a completely different asset**.
That is the point: several versions coexist in one scene, a newly created node
gets the new version, and nodes already placed keep the old one. Nothing breaks
retroactively.

The judgement, which SideFX states outright: **a disruptive change is the only
good reason to bump.** Do not bump for additions. Houdini itself accumulated only
about four versions of a node across many years of breaking changes. A repository
full of `::2.0`, `::3.0`, `::4.0` is version-as-changelog, and it charges every
user a migration for nothing.

## Inside the asset

The node-first rule matters twice over here: a network of visible nodes is
debuggable by whoever inherits the asset, an opaque wrangle is not. Use
block_begin/block_end for per-piece work rather than VEX loops.

- Label the internals. null SOPs as waypoints named OUTPUT and INPUT_GEO, so the next person can read the graph without opening every node.
- Every tweakable is a promoted parameter. A file path or magic number buried in the network is the bug reported six months later, from a different show.
- Promote in one call with create_spare_parameters (plural), using folder_name to group them into tabs. A flat wall of forty parameters is a usability defect.
- Ship a help card via set_hda_section_content. An asset without one gets used wrongly rather than not at all.

## Order of work

1. list_node_types first, to confirm the type name is free.
2. Build the logic in a subnet and test it against several inputs with `get_geometry_info` or `get_stage_info` BEFORE converting. Debugging inside a definition is harder than debugging outside one.
3. Promote parameters, grouped into tabs.
4. `create_hda` with a namespace, then `get_hda_info` to verify the definition is what you think it is.
5. `get_hda_sections`, then `set_hda_section_content` for the help card.
6. `update_hda` for later changes, and bump the version only for a disruptive one.

{network_housekeeping}
