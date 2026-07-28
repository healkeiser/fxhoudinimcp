You are building or assigning materials in Houdini.

Goal: {description}

`shade/basics` covers assigning, `shade/build` and `shade/layering` building,
`shade/parms` and `shade/vops` the shader interface, `shade/textures`,
`shade/normalmaps`, `shade/modulate`, `shade/convert` and `shade/ptex` texturing,
`shade/overrides` and `shade/stylesheets` per-object variation. Read with
get_help_page.

**Scope warning:** this corpus is titled *Mantra materials*. For a **Karma or
MaterialX** look the authority is `solaris/`, a materiallibrary LOP in /stage and
mtlxstandard_surface, not these pages. Check what the scene renders with before
following anything here. Building a Mantra shader for a Karma render is a
whole-day mistake.

## Judgement

- Assign, then author. Get a material bound and visible before making it good; an unassigned beautiful shader looks identical to no shader.
- Layering is a first-class approach, not a workaround. `shade/layering` before hand-mixing shader outputs.
- Textures need UVs, so UV work belongs upstream in SOPs and is not a shading fix. `shade/textures` and `shade/convert` on formats and conversion.
- Normal maps have a tangent-space convention that must match how the map was authored; `shade/normalmaps` exists because guessing produces inverted detail that reads as a lighting bug.
- **Stylesheets and overrides** are how one material serves many objects with variation. Reach for them before duplicating a shader per variant, exactly as you reach for attributes before duplicating a branch in SOPs.
- Expose shader controls as parameters (`shade/parms`) so lookdev is a parameter change and not a graph edit.

## Order of work

1. get_scene_info and get_render_settings to establish the renderer. This decides which toolset is even correct.
2. list_materials and get_material_info to see what already exists rather than adding a duplicate.
3. Create and **assign** with create_material and assign_material, then look at it with the viewport renderer and capture_screenshot.
4. Author the surface: base colour, then roughness and specular, then detail maps. Judge each against a lit render, not the network.
5. Promote the controls you will actually tweak.
6. Use overrides or stylesheets for per-object variation instead of copies.

{network_housekeeping}
