"""MCP prompt templates for common Houdini workflows.

These prompts guide AI assistants through multi-step Houdini tasks.

Markdown filenames follow SideFX's own help scope names, so ``pyro.md`` is the
prompt for the corpus at ``pyro/`` and ``solaris.md`` for ``solaris/``. That
keeps one obvious home per subject and makes the "read the shipped page" advice
inside each prompt checkable. Files starting with an underscore are shared
includes rather than prompts. The public prompt function names predate the
convention and are deliberately unchanged, because clients call them.
"""

from __future__ import annotations

# Internal
from fxhoudinimcp._loader import _MD_DIR, load_markdown, markdown_exists
from fxhoudinimcp.server import mcp

# What the user calls a sim versus the corpus that documents it. SideFX files
# FLIP under fluid/ and RBD under destruction/, and users ask for "flip" and
# "rbd", so the mapping has to exist somewhere; here is better than making
# every caller know it.
_SIM_ALIASES = {
    "smoke": "pyro",
    "fire": "pyro",
    "explosion": "pyro",
    "flip": "fluid",
    "liquid": "fluid",
    "water": "fluid",
    "ocean": "fluid",
    "whitewater": "fluid",
    "cloth": "vellum",
    "softbody": "vellum",
    "rbd": "destruction",
    "fracture": "destruction",
    "bullet": "destruction",
    "sand": "mpm",
    "snow": "mpm",
}


@mcp.prompt()
def procedural_modeling_workflow(
    description: str,
    output_context: str = "/obj",
) -> str:
    """Guide for building a procedural modeling network in SOPs.

    Args:
        description: What geometry to create (e.g. "a rocky terrain with scattered trees")
        output_context: Where to create the geo container
    """
    return load_markdown(
        "workflows/model.md",
        description=description,
        output_context=output_context,
    )


@mcp.prompt()
def usd_scene_assembly(
    scene_description: str,
) -> str:
    """Guide for building a USD scene in Houdini's LOPs/Solaris.

    Args:
        scene_description: Description of the USD scene to build
    """
    return load_markdown(
        "workflows/solaris.md",
        scene_description=scene_description,
    )


@mcp.prompt()
def simulation_setup(
    sim_type: str,
    description: str = "",
) -> str:
    """Guide for setting up a dynamics simulation.

    Dispatches to the solver-specific guide when one exists, because a single
    generic file had to cover pyro, FLIP, Vellum, RBD and MPM at once and so
    could not say more than a table row about any of them. Houdini ships a
    separate manual per solver, and these files mirror that split. Anything
    without its own guide falls back to dyno.md, the general dynamics one.

    Args:
        sim_type: Type of simulation (pyro, flip, rbd, vellum, mpm, pop)
        description: Additional context about the simulation
    """
    key = sim_type.strip().lower()
    scope = _SIM_ALIASES.get(key, key)
    candidate = f"workflows/{scope}.md"
    return load_markdown(
        candidate if markdown_exists(candidate) else "workflows/dyno.md",
        sim_type=sim_type,
        description=description or f"Create a {sim_type} simulation",
    )


@mcp.prompt()
def pdg_pipeline(
    task_description: str,
) -> str:
    """Guide for building a PDG/TOPs pipeline.

    Args:
        task_description: What the pipeline should accomplish
    """
    return load_markdown(
        "workflows/tops.md",
        task_description=task_description,
    )


@mcp.prompt()
def hda_development(
    asset_description: str,
    context: str = "Sop",
) -> str:
    """Guide for creating a Houdini Digital Asset.

    Args:
        asset_description: What the HDA should do
        context: Node context for the HDA (Sop, Lop, Object, etc.)
    """
    return load_markdown(
        "workflows/assets.md",
        asset_description=asset_description,
        context=context,
    )


@mcp.prompt()
def copernicus_workflow(
    description: str,
) -> str:
    """Guide for image work in Copernicus (COPs).

    Args:
        description: What to build (e.g. "a tileable rust texture")
    """
    return load_markdown(
        "workflows/copernicus.md",
        description=description,
    )


@mcp.prompt()
def heightfield_terrain(
    description: str,
) -> str:
    """Guide for building terrain with heightfields.

    Args:
        description: The terrain to build (e.g. "an eroded desert mesa")
    """
    return load_markdown(
        "workflows/heightfields.md",
        description=description,
    )


@mcp.prompt()
def houdini_workflow(
    topic: str,
    description: str = "",
) -> str:
    """Guide for any Houdini subject the shipped manual documents.

    One entry point rather than a function per subject, so a new corpus needs a
    markdown file and nothing else. `topic` is the SideFX help scope name, which
    is also the markdown filename: character, render, shade, crowds, copy, props,
    dopparticles, io, anim, ocean, grains, muscles, finiteelements, feathers,
    fur, ml, composite, heightfields_cop, plus every subject that has its own
    named prompt (pyro, fluid, vellum, destruction, mpm, solaris, tops, model,
    assets, copernicus, heightfields, dyno, troubleshooting).

    Args:
        topic: Help scope name for the subject, e.g. "character" or "render"
        description: What you are trying to build
    """
    key = topic.strip().lower().replace("/", "")
    candidate = f"workflows/{key}.md"
    if not markdown_exists(candidate):
        available = sorted(path.stem for path in (_MD_DIR / "workflows").glob("*.md"))
        raise ValueError(
            f"No workflow guide for '{topic}'. Available topics: {available}. "
            "search_help(query) covers subjects with no guide."
        )
    return load_markdown(
        candidate,
        topic=topic,
        description=description or f"Work on {topic}",
    )


@mcp.prompt()
def debug_scene(
    problem_description: str = "general issues",
) -> str:
    """Systematic approach to debugging a Houdini scene.

    Args:
        problem_description: What problem the user is experiencing
    """
    return load_markdown(
        "workflows/troubleshooting.md",
        problem_description=problem_description,
    )
