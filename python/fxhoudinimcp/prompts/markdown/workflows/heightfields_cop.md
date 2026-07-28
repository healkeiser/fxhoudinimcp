You are working on terrain inside Copernicus (COP heightfields).

Goal: {description}

This is the Copernicus-based terrain toolset, distinct from the SOP heightfield
nodes. Read the pages in this corpus with get_help_page, and for the SOP side use
the heightfields workflow instead.

Two things to establish before building anything:

- **Which toolset the shot needs.** SOP heightfields (`heightfields/`) and COP heightfields are different implementations of the same idea. Mixing them mid-network means converting between representations.
- **That Copernicus rules apply here.** The spaces, windows, multiple-output and display-flag behaviour from `copernicus/spaces` and `copernicus/working_with_cops` all govern this work. A COP heightfield setup that looks wrongly framed or cropped is a data-window problem, exactly as any other COP is.

## Judgement

- Terrain in COPs is layered image data, so the layer discipline from SOP heightfields carries over: keep a mask you need in its own named layer rather than in a shared channel.
- Copernicus is GPU-based, which changes the cost model relative to SOP heightfields. Resolution is still the dominant cost, and erosion is still the expensive stage.
- Visualisation is not the data. Height displays as a hillshade in the Composite Viewer, so inspect actual values before concluding a shaping node did nothing.
- Decide the output early: staying in COPs, converting to SOP heightfields, or writing an image. It changes how the network is built.

## Order of work

1. `list_node_types(context='Cop', filter='heightfield')` to see what the running version actually provides, rather than assuming parity with the SOP set.
2. Establish resolution and window first.
3. Base shape, then masks in named layers, then shaping.
4. Inspect real pixel values at milestones, and `capture_screenshot`.
5. Convert or write out, and cache upstream of anything expensive.

{network_housekeeping}
