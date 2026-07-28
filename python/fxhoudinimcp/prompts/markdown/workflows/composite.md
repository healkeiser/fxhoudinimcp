You are working with Houdini's older compositing networks (COP2).

Goal: {description}

**Read this first: SideFX marks this toolset deprecated.** `composite/index`
itself opens by including a deprecation notice, and the corpus contains
`composite/_old_cops_deprecated`. **Copernicus is the current compositor**, so
unless the task is specifically maintaining an existing COP2 network, use the
copernicus workflow instead of this one.

Legitimate reasons to be here: an existing scene uses COP2 and must keep working,
or a node exists only in COP2. Everything else belongs in Copernicus.

If you are staying: `composite/load` and `composite/save` for I/O,
`composite/layers` for combining, `composite/planes` and `composite/multi` for
image structure, `composite/keying`, `composite/mattes`, `composite/masks`,
`composite/color_correct`, `composite/blur_sharpen`, `composite/distort`,
`composite/lens_effects`, `composite/luts`, `composite/comp_vops`,
`composite/performance` and `composite/tips`. `composite/comp_terms` is the
glossary.

## The shape of a COP2 network

- Load image data, modify it, and **set the render flag** on the node that provides the final output. The render flag, not the display flag, is what defines the network's result.
- Planes are the structure images carry, and multi-plane work (`composite/planes`, `composite/multi`) is how render passes are handled rather than as separate files.
- Output either to image files, or back into Houdini via `composite/export`.

## Judgement

- Before adding anything to a COP2 network, ask whether the whole task should move to Copernicus. Extending a deprecated network is a cost paid repeatedly.
- `composite/performance` exists because COP2 is CPU-bound in ways Copernicus is not. A slow COP2 network is often an argument for migrating rather than optimising.
- Keying, mattes and masks are three different concepts; the glossary is worth reading before mixing the terms in a setup.

## Order of work

1. Establish that COP2 is genuinely required. Say why, in one sentence, before building.
2. Load, then inspect the planes present rather than assuming RGBA.
3. Build the chain, and set the render flag on the output node.
4. Verify visually with capture_screenshot.
5. Save, or export back into the scene.

{network_housekeeping}
