"""Wide performance sweep over handlers, run under hython:

    hython tests/integration/perf_sweep.py
    hython tests/integration/perf_sweep.py --profile workflow.setup_render

Builds realistic scenes (a 250k-point grid, a 300-node network, a heavy
solver node) and times a broad set of commands through the dispatcher.
With --profile, cProfile output for that single command is printed
instead of the sweep table.
"""

from __future__ import annotations

# Built-in
import cProfile
import os
import pstats
import sys
import time

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "houdini", "scripts", "python"),
)

import fxhoudinimcp_server.dispatcher as dispatcher  # noqa: E402
import fxhoudinimcp_server.handlers  # noqa: E402, F401
import hou  # noqa: E402

dispatcher.HAS_HDEFEREVAL = False

RESULTS: list[tuple[str, float | None, str | None]] = []
PROFILE_CMD = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--profile" else None


def call(command: str, label: str = "", reps: int = 3, **params):
    """Dispatch *command*, record best-of-*reps* wall time in ms."""
    name = f"{command} {label}".strip()
    if PROFILE_CMD and command == PROFILE_CMD:
        profiler = cProfile.Profile()
        profiler.enable()
        result = dispatcher.dispatch(command, params)
        profiler.disable()
        stats = pstats.Stats(profiler, stream=sys.stdout)
        stats.sort_stats("cumulative").print_stats(30)
        return result.get("data")

    best = None
    result = None
    for _ in range(reps):
        start = time.perf_counter()
        result = dispatcher.dispatch(command, params)
        elapsed = (time.perf_counter() - start) * 1000
        best = elapsed if best is None else min(best, elapsed)
        if result["status"] != "success":
            RESULTS.append((name, None, result["error"]["message"][:90]))
            return None
    RESULTS.append((name, best, None))
    return result["data"]


def fresh():
    hou.hipFile.clear(suppress_save_prompt=True)


def main() -> None:
    print(f"Houdini {hou.applicationVersionString()}")

    ###### Node operations on a 300-node network

    fresh()
    call("nodes.create_node", parent_path="/obj", node_type="geo", name="big", reps=1)
    prev = None
    for i in range(300):
        node = hou.node("/obj/big").createNode("null", f"n{i}")
        if prev is not None:
            node.setInput(0, prev)
        prev = node
    call("nodes.list_children", label="(300 nodes)", parent_path="/obj/big")
    call(
        "nodes.list_children",
        label="(300 nodes, recursive from /)",
        parent_path="/",
        recursive=True,
    )
    call("nodes.find_nodes", label="(over 300 nodes)", pattern="n1*")
    call("nodes.layout_children", label="(300 nodes)", parent_path="/obj/big", reps=1)
    call("nodes.list_node_types", label="(Sop, full)", context="Sop", limit=5000)
    call(
        "nodes.create_node",
        label="(null into 300-node net)",
        parent_path="/obj/big",
        node_type="null",
        reps=1,
    )

    ###### Parameter operations on a parameter-heavy node

    fresh()
    call("nodes.create_node", parent_path="/obj", node_type="geo", name="g", reps=1)
    solver = None
    for type_name in ("pyrosolver::3.0", "pyrosolver", "vellumsolver", "mountain"):
        try:
            solver = hou.node("/obj/g").createNode(type_name)
            break
        except hou.OperationFailed:
            continue
    parm_count = len(solver.parms())
    call("nodes.get_node_info", label=f"(pyrosolver, {parm_count} parms)", node_path=solver.path())
    call(
        "parameters.get_parameter_schema",
        label=f"(pyrosolver, {parm_count} parms, full)",
        node_path=solver.path(),
    )
    call(
        "parameters.get_parameter_schema",
        label="(pyrosolver, filtered)",
        node_path=solver.path(),
        filter="temp",
    )
    call("parameters.get_parameter", node_path=solver.path(), parm_name="timescale")
    call("parameters.set_parameter", node_path=solver.path(), parm_name="timescale", value=1.5)
    call("context.explain_node", label="(pyrosolver)", node_path=solver.path())

    ###### Geometry reads on a 250k-point grid

    fresh()
    call("nodes.create_node", parent_path="/obj", node_type="geo", name="dense", reps=1)
    grid = hou.node("/obj/dense").createNode("grid")
    grid.parmTuple("size").set((10, 10))
    grid.parm("rows").set(500)
    grid.parm("cols").set(500)
    color = hou.node("/obj/dense").createNode("color")
    color.setInput(0, grid)
    color.setDisplayFlag(True)
    color.setRenderFlag(True)
    gpath = color.path()
    hou.node(gpath).geometry()  # pre-cook so timings exclude the cook

    call("geometry.get_geometry_info", label="(250k pts)", node_path=gpath)
    call("geometry.get_points", label="(250k pts, page 1000, P only)", node_path=gpath)
    call(
        "geometry.get_points",
        label="(250k pts, page 1000, +Cd)",
        node_path=gpath,
        attributes=["Cd"],
    )
    call(
        "geometry.get_points",
        label="(250k pts, page 1000, offset 200k)",
        node_path=gpath,
        start=200_000,
    )
    call("geometry.get_points", label="(250k pts, page 10000)", node_path=gpath, count=10_000)
    call("geometry.get_prims", label="(249k prims, page 1000)", node_path=gpath)
    call("geometry.get_attrib_values", label="(P, page 200)", node_path=gpath, attrib_name="P")
    call(
        "geometry.get_attrib_values",
        label="(P, page 200, offset 200k)",
        node_path=gpath,
        attrib_name="P",
        start=200_000,
    )
    call("geometry.sample_geometry", label="(100 of 250k)", node_path=gpath, sample_count=100)
    call("geometry.get_bounding_box", label="(250k pts)", node_path=gpath)
    call(
        "geometry.find_nearest_point", label="(250k pts)", node_path=gpath, position=[1.0, 0.0, 1.0]
    )
    call("geometry.get_prim_intrinsics", label="(summary)", node_path=gpath)

    ###### Context / scene summaries

    call("context.get_scene_summary", label="(dense scene)")
    call("context.get_network_overview", label="(dense scene)", root_path="/obj")
    call("scene.get_scene_info")
    call("scene.get_context_info", label="(/obj)", context="/obj")

    ###### VEX

    call(
        "vex.create_wrangle",
        label="(first)",
        parent_path="/obj/dense",
        vex_code="@Cd = {1,0,0};",
        reps=1,
    )
    wrangle = call(
        "vex.create_wrangle",
        label="(second)",
        parent_path="/obj/dense",
        vex_code="@Cd = {0,1,0};",
        reps=1,
    )
    if wrangle:
        call("vex.validate_vex", node_path=wrangle["node_path"])

    ###### Materials / HDAs / rendering / takes / animation

    fresh()
    call("materials.list_material_types", reps=1)
    call("materials.list_materials", reps=1)
    call("hda.list_installed_hdas", reps=1)
    call("rendering.list_render_nodes", reps=1)
    call("takes.list_takes", reps=1)
    call("nodes.create_node", parent_path="/obj", node_type="geo", name="anim", reps=1)
    call(
        "animation.set_keyframe", node_path="/obj/anim", parm_name="tx", frame=10, value=5.0, reps=1
    )
    call("animation.get_keyframes", node_path="/obj/anim", parm_name="tx", reps=1)

    ###### Workflows (create-heavy, 1 rep each in a fresh scene)

    fresh()
    call("workflow.create_material", label="(principled)", name="m1", reps=1)
    chain_geo = hou.node("/obj").createNode("geo", "chain")
    call(
        "workflow.build_sop_chain",
        label="(10 nodes)",
        parent_path=chain_geo.path(),
        reps=1,
        steps=[{"type": "box"}] + [{"type": "null"} for _ in range(9)],
    )
    fresh()
    sphere_geo = hou.node("/obj").createNode("geo", "src")
    sphere = sphere_geo.createNode("sphere")
    call("workflow.setup_pyro_sim", reps=1, source_geo=sphere.path())
    fresh()
    call("workflow.setup_rbd_sim", label="(box)", reps=1, geo_path=_boxed_geo())
    fresh()
    call("workflow.setup_render", label="(karma)", reps=1, renderer="karma", samples=8)
    fresh()
    call("workflow.setup_render", label="(mantra)", reps=1, renderer="mantra", samples=8)

    ###### LOPs / COPs

    fresh()
    lopnet = hou.node("/obj").createNode("lopnet", "lops")
    call("lops.create_lop_node", parent_path=lopnet.path(), lop_type="sphere", reps=1)
    sphere_lop = hou.node(lopnet.path()).children()[0]
    call("lops.get_stage_info", node_path=sphere_lop.path())
    call("lops.list_usd_prims", node_path=sphere_lop.path())
    call("lops.create_light_rig", label="(3-point)", parent_path=lopnet.path(), reps=1)

    ###### Report

    print()
    print(f"{'command':<64} {'best ms':>10}")
    print("-" * 76)
    for name, ms, error in sorted(RESULTS, key=lambda r: -(r[1] or 0)):
        if error is not None:
            print(f"{name:<64} {'ERROR':>10}  {error}")
        else:
            print(f"{name:<64} {ms:>10.1f}")


def _boxed_geo() -> str:
    geo = hou.node("/obj").createNode("geo", "rbd_src")
    geo.createNode("box")
    return geo.path()


if __name__ == "__main__":
    main()
