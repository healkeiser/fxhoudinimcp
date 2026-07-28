You are working with Houdini properties (render, shading, light and camera options).

Goal: {description}

`props/index` is the concept page, with sections on inheritance order, editing,
per-primitive properties and advanced uses. `props/mantra`, `props/material`,
`props/obj`, `props/viewport`, `props/alembic` and `props/vop` list what exists
per area. Read with get_help_page.

## What properties actually are

Properties supply options **to the renderer**: camera parameters, light positions
and settings, shader names. Many are renderer-specific. Some, like camera focal
length, are common to every renderer and are translated automatically, because the
properties system maintains a map between what the renderer knows and what Houdini
defines.

That mapping is the reason properties exist as a separate concept rather than as
ordinary parameters, and the reason a property can be present and still not reach
the renderer: the map has to know about it.

## Inheritance is the whole mechanism

Properties form a hierarchy and resolve by **inheritance order** (`props/index`).
Setting the same property in two places is not a conflict to be avoided, it is the
intended way to express a default plus an exception. Set the general case high and
the exception low.

**Per-primitive properties** push this further: one object can carry different
values per primitive, which is how one piece of geometry gets several shading
behaviours without being split apart.

## Judgement

- Before adding a property, check whether one already applies by inheritance. A locally added property that duplicates an inherited value is invisible until someone changes the parent and nothing happens.
- get_parameter_schema is how you discover the real property name on a node. Property names are not guessable and several look almost identical across renderers.
- A property that appears to do nothing is usually either renderer-specific and unmapped for the current renderer, or overridden lower down.

## Order of work

1. get_render_settings to know which renderer's properties are in play.
2. Look for an inherited value before adding one.
3. Add at the highest level that is still correct, then override lower only for genuine exceptions.
4. get_parameter_schema to confirm the exact name, then set it.
5. Verify in a render or viewport render, not by reading the parameter back.

{network_housekeeping}
