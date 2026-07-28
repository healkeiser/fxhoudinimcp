You are copying or instancing geometry in Houdini.

Goal: {description}

`copy/index` states the distinction, `copy/copytopoints`, `copy/duplicate`,
`copy/instancing`, `copy/delayedload`, `copy/instanceattrs`, `copy/varying` and
`copy/packed_and_soups` cover the cases. Read with get_help_page.

## The distinction that decides the whole setup

- **Copying** creates copies of the source on each point of the destination, and they are **actual geometry in the scene** that you can keep modelling with. The cost is real: Houdini has to cook and display all of it.
- **Point instancing** copies **at render time**. Each copy exists only momentarily, as its area of the image is rendered. The geometry appears in the render and **not in the viewer**.

So the question is never "which is faster". It is: does anything downstream, or
any solver, or the artist's eye in the viewport, need these copies to exist? If
yes, copy. If only the renderer needs them, instance.

## Choosing the node

- **copytopoints** for copies onto target points. With Pack and Instance enabled it packs the source once and shares the reference between copies, which is the cheap form of real geometry.
- **duplicate** when there are no target points at all and you just want N of something transformed.
- Point instancing via an instance object when the copies only ever need to exist in the render.
- **delayedload** keeps the instanced geometry on disk instead of in the hip file, which is what stops a forest scene becoming a gigabyte.

## Variation without a switch rig

- copytopoints' own Piece Attribute (`useidattrib` on, `idattrib` naming it) sends each source piece to the target points whose value matches, with all variants merged into the first input. A merged variant pile plus one integer attribute replaces any switch-and-loop rig.
- Continuous per-point variation (pscale, orientation, colour) is attribrandomize.
- Per-copy attributes for instancing have their own conventions; `copy/instanceattrs` is the page, and guessing attribute names here is how instancing silently ignores your variation.
- **Copy stamping is superseded** and must not be used. `copy/tutorial_stamping` exists for reading old scenes, not for authoring new ones. Use a for-each loop when copies must differ structurally.

## Order of work

1. Decide copy versus instance before building, using the test above.
2. Build one source and get it right. Variation comes after a single copy is correct.
3. Scatter or otherwise create the target points, then copytopoints.
4. Add variation by attribute, not by duplicating branches.
5. get_geometry_info to check the count is what you intended before anything downstream.

{network_housekeeping}
