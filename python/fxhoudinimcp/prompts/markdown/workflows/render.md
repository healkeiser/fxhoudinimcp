You are setting up rendering in Houdini.

Goal: {description}

`render/tips` is SideFX's production workflow page, with sections on models, look
development, scene assembly, effects, lighting and rendering. `render/quality`,
`render/sampling`, `render/understanding`, `render/volumes`,
`render/renderingmanypolys` and `render/cameras` cover specifics. Read with
get_help_page.

**Scope warning worth stating up front:** this corpus is Mantra-centred (`ifd`,
`soho`, `renderman`). If the shot renders in **Karma**, the authority is
`solaris/` and the karmarendersettings LOP, not these pages. Check which renderer
the scene actually uses with get_render_settings before following a page here.

## How the efficient workflow changed, and why it matters

Before Houdini 13 the efficient approach was proxy geometry in the viewport,
swapped at render time by a delayed load procedural or point instancing. Houdini
13 added **packed primitives** and deep **Alembic** integration, and those let you
work with very large geometry directly rather than proxying it.

The pipeline consequence, which is the actual point of `render/tips`: **sharing
Alembic geometry lets several departments work in parallel** on the same asset
instead of serialising behind one another. Reach for packed primitives and Alembic
before building a proxy-and-swap rig, because the swap rig is solving a problem
that mostly went away.

## Judgement

- Sampling and quality are separate knobs from resolution, and raising resolution to fix noise is the classic waste. `render/sampling` and `render/quality` before touching either.
- Volumes render differently from surfaces and have their own page. Do not tune a volume render with surface intuitions.
- Points and particles in large numbers have a dedicated section in `render/tips`; the naive approach does not scale.
- Deep output, cryptomatte and LPE exist so comp can fix things without a re-render. Setting them up before the first hero render is cheaper than after.
- Render to disk only when asked. For look iteration, set_viewport_renderer plus capture_screenshot is the loop.

## Order of work

1. get_render_settings and get_scene_info to establish what renderer and what settings exist. Do not assume Mantra or Karma.
2. Cameras and framing before light, light before material, material before sampling. Each of those invalidates judgements about the next.
3. Preview in the viewport, not on disk.
4. Sampling and quality last, once the image is right and only the noise is wrong.
5. start_render with a written frame range and output path, and get_render_progress rather than guessing at completion.

{network_housekeeping}
