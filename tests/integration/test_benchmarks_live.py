"""Micro-benchmarks for handler hot paths.

These never fail on timing — they print a report (run with ``-s``) and
only assert correctness invariants. The per-command dispatch timings are
also aggregated in the session summary (see conftest).
"""

from __future__ import annotations

# Built-in
import time

# Third-party
import hou
import pytest

pytestmark = pytest.mark.integration


def _timed(label: str, fn, *args, **kwargs):
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed = (time.perf_counter() - start) * 1000
    print(f"[bench] {label:<52} {elapsed:>10.1f} ms")
    return result, elapsed


class TestBenchmarks:
    def test_create_node_latency_growth(self, call):
        """create_node lays out + pans after every call — cost grows with
        network size. Measure first vs thirtieth node."""
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="bench")[
            "node_path"
        ]
        timings = []
        for index in range(30):
            _, elapsed = _timed(
                f"create_node #{index + 1}",
                call,
                "nodes.create_node",
                parent_path=geo,
                node_type="null",
            )
            timings.append(elapsed)
        first, last = timings[0], timings[-1]
        print(
            f"[bench] create_node growth: first={first:.1f}ms "
            f"last={last:.1f}ms ratio={last / max(first, 0.001):.1f}x"
        )
        assert len(hou.node(geo).children()) == 30

    def test_list_node_types_full_sop_dump(self, call):
        data, _ = _timed(
            "list_node_types Sop (no filter, limit=5000)",
            call,
            "nodes.list_node_types",
            context="Sop",
            limit=5000,
        )
        print(f"[bench] Sop types: total={data['total_count']} returned={data['returned_count']}")
        assert data["total_count"] > 200

    def test_get_points_pagination_on_dense_grid(self, call):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="grid_geo")[
            "node_path"
        ]
        grid = call("nodes.create_node", parent_path=geo, node_type="grid")
        call(
            "parameters.set_parameters",
            node_path=grid["node_path"],
            params={"rows": 300, "cols": 300},
        )
        data, _ = _timed(
            "get_points on 90k-point grid (default page)",
            call,
            "geometry.get_points",
            node_path=grid["node_path"],
        )
        points = data.get("points", [])
        print(f"[bench] page size returned: {len(points)}")
        assert points

    def test_workflow_setup_costs(self, call):
        geo = call("nodes.create_node", parent_path="/obj", node_type="geo", name="geo1")[
            "node_path"
        ]
        sphere = call("nodes.create_node", parent_path=geo, node_type="sphere")
        _timed(
            "workflow.setup_pyro_sim",
            call,
            "workflow.setup_pyro_sim",
            source_geo=sphere["node_path"],
        )
        _timed(
            "workflow.build_sop_chain (10 nodes)",
            call,
            "workflow.build_sop_chain",
            parent_path=geo,
            steps=[{"type": "null"} for _ in range(10)],
        )

    def test_execute_python_overhead(self, call):
        _, elapsed = _timed(
            "code.execute_python (trivial)",
            call,
            "code.execute_python",
            code="x = 1 + 1",
            return_expression="x",
        )
        assert elapsed < 5000
