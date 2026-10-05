"""A write inside a DOP network names the simulation whose cooked frames it leaves stale.

A parameter written into a node inside a DOP network does not reset the
simulation's cache. Measured on Houdini 22.0.429: a POP source's impulserate
changed 100 -> 400 -> 50 -> 250, and frame 25 held 100 particles throughout,
whatever frames were visited in between; a bare parm.set() plus
hou.setFrame() did the same. Only a reset brought the new value. The replies
said nothing, and a caller read the old frames as the result of its change.

set_parameter, set_parameters, create_node, connect_nodes and build_network
now carry `simulation_cache` when they touch a node inside a DOP network: the
node reset_simulation presses for it, and a note. hou is mocked here.
"""

from __future__ import annotations

# Built-in
import os
import sys
from unittest.mock import MagicMock

# Third-party
import pytest

sys.modules.setdefault("hou", MagicMock())
sys.modules.setdefault("hdefereval", MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "houdini", "scripts", "python"))

# Internal
import fxhoudinimcp_server.handlers.dop_handlers as dops  # noqa: E402
import fxhoudinimcp_server.handlers.graph_handlers as graph  # noqa: E402
import fxhoudinimcp_server.handlers.node_handlers as nodes  # noqa: E402
import fxhoudinimcp_server.handlers.parameter_handlers as parameters  # noqa: E402

hou = dops.hou


class _Node:
    """A node with a category, a parent, and optionally a Reset Simulation button."""

    def __init__(self, path, category="Sop", parent=None, resimulate=False):
        self._path = path
        self._category = category
        self._parent = parent
        self.resimulate = MagicMock() if resimulate else None

    def path(self):
        return self._path

    def name(self):
        return self._path.rsplit("/", 1)[-1]

    def parent(self):
        return self._parent

    def parm(self, name):
        return self.resimulate if name == "resimulate" else None

    def type(self):
        node_type = MagicMock()
        node_type.category.return_value = self._category
        node_type.name.return_value = self.name().rstrip("0123456789")
        return node_type

    def position(self):
        return (0.0, 0.0)


@pytest.fixture(autouse=True)
def dop_category(monkeypatch):
    monkeypatch.setattr(hou, "dopNodeTypeCategory", lambda: "Dop", raising=False)


@pytest.fixture
def pop_source():
    """/obj/geo1/popnet (a SOP-level solver with the button) > dopnet > source1."""
    popnet = _Node("/obj/geo1/popnet", category="Sop", resimulate=True)
    dopnet = _Node("/obj/geo1/popnet/dopnet", category="Dop", parent=popnet)
    source = _Node("/obj/geo1/popnet/dopnet/source1", category="Dop", parent=dopnet)
    return popnet, dopnet, source


class TestTheNote:
    def test_a_dop_node_names_the_node_reset_simulation_presses(self, pop_source):
        popnet, _, source = pop_source
        note = dops.dop_cache_note([source])
        assert note["networks"] == [popnet.path()]
        assert "reset_simulation" in note["note"]

    def test_a_node_outside_a_simulation_adds_nothing(self):
        assert dops.dop_cache_note([_Node("/obj/geo1/box1")]) is None
        assert dops.dop_cache_note([]) is None

    def test_one_network_is_named_once(self):
        dopnet = _Node("/obj/dopnet1", category="Object", resimulate=True)
        members = [_Node(f"/obj/dopnet1/n{i}", category="Dop", parent=dopnet) for i in range(3)]
        assert dops.dop_cache_note(members)["networks"] == ["/obj/dopnet1"]

    def test_reset_simulation_takes_the_named_network(self, monkeypatch, pop_source):
        popnet, _, source = pop_source
        named = dops.dop_cache_note([source])["networks"][0]
        monkeypatch.setattr(hou, "node", {named: popnet}.get)
        monkeypatch.setattr(hou.playbar, "frameRange", lambda: (1.0, 240.0))
        monkeypatch.setattr(hou, "setFrame", lambda frame: None)
        result = dops._reset_simulation(named)
        assert result["reset_node"] == named
        popnet.resimulate.pressButton.assert_called_once_with()


class TestParameterWrites:
    @pytest.fixture
    def written(self, monkeypatch, pop_source):
        _, _, source = pop_source
        parm = MagicMock()
        parm.node.return_value = source
        source.parm = lambda name: parm if name == "impulserate" else None
        monkeypatch.setattr(parameters, "_resolve_node", lambda path: source)
        monkeypatch.setattr(parameters, "_resolve_parm", lambda path, name: parm)
        monkeypatch.setattr(parameters, "_write_parm", lambda p, value, *args: {"new_value": value})
        return source

    def test_set_parameter_names_the_simulation(self, written, pop_source):
        result = parameters._set_parameter(written.path(), "impulserate", 400)
        assert result["simulation_cache"]["networks"] == [pop_source[0].path()]

    def test_a_tuple_write_names_it_too(self, written, monkeypatch, pop_source):
        monkeypatch.setattr(parameters, "_set_tuple", lambda *args: ([1.0, 2.0, 3.0], {}))
        result = parameters._set_parameter(written.path(), "force", [1, 2, 3])
        assert result["simulation_cache"]["networks"] == [pop_source[0].path()]

    def test_set_parameters_names_it_once_for_the_batch(self, written, pop_source):
        result = parameters._set_parameters(written.path(), {"impulserate": 400})
        assert result["simulation_cache"]["networks"] == [pop_source[0].path()]

    def test_a_batch_that_wrote_nothing_says_nothing(self, written, monkeypatch):
        def refuse(parm, value, *args):
            raise ValueError("locked")

        monkeypatch.setattr(parameters, "_write_parm", refuse)
        result = parameters._set_parameters(written.path(), {"impulserate": 400})
        assert result["set"] == [] and "simulation_cache" not in result

    def test_a_sop_write_says_nothing(self, monkeypatch):
        box = _Node("/obj/geo1/box1")
        parm = MagicMock()
        parm.node.return_value = box
        monkeypatch.setattr(parameters, "_resolve_parm", lambda path, name: parm)
        monkeypatch.setattr(parameters, "_write_parm", lambda p, value, *args: {"new_value": 1})
        assert "simulation_cache" not in parameters._set_parameter(box.path(), "sizex", 1)


class TestNodeEdits:
    @pytest.fixture(autouse=True)
    def quiet_editor(self, monkeypatch):
        monkeypatch.setattr(nodes, "_focus_network_editor", lambda *args, **kwargs: None)
        monkeypatch.setattr(nodes, "place_new_node", lambda node: None)

    def test_create_node_in_a_dop_network_names_it(self, monkeypatch, pop_source):
        popnet, dopnet, source = pop_source
        dopnet.createNode = lambda node_type, node_name=None: source
        monkeypatch.setattr(nodes, "_get_node", lambda path: dopnet)
        result = nodes.create_node(dopnet.path(), "popsource")
        assert result["simulation_cache"]["networks"] == [popnet.path()]

    def test_create_node_in_a_sop_network_says_nothing(self, monkeypatch):
        geo = _Node("/obj/geo1", category="Object")
        geo.createNode = lambda node_type, node_name=None: _Node("/obj/geo1/box1", parent=geo)
        monkeypatch.setattr(nodes, "_get_node", lambda path: geo)
        assert "simulation_cache" not in nodes.create_node(geo.path(), "box")

    def test_connect_nodes_into_a_dop_node_names_it(self, monkeypatch, pop_source):
        popnet, dopnet, source = pop_source
        solver = _Node("/obj/geo1/popnet/dopnet/popsolver1", category="Dop", parent=dopnet)
        solver.setInput = MagicMock()
        monkeypatch.setattr(nodes, "_get_node", {solver.path(): solver, source.path(): source}.get)
        monkeypatch.setattr(nodes, "_resolve_source", lambda *args: source)
        result = nodes.connect_nodes(source.path(), solver.path(), input_index=2)
        solver.setInput.assert_called_once_with(2, source, 0)
        assert result["simulation_cache"]["networks"] == [popnet.path()]


class _DopParent:
    """A DOP network for build_network: createNode hands out prepared nodes."""

    def __init__(self, dopnet, made):
        self._dopnet = dopnet
        self._made = iter(made)

    def path(self):
        return self._dopnet.path()

    def childTypeCategory(self):  # noqa: N802 - HOM spelling
        category = MagicMock()
        category.name.return_value = "Dop"
        return category

    def children(self):
        return []

    def displayNode(self):  # noqa: N802 - HOM spelling
        return None

    def renderNode(self):  # noqa: N802 - HOM spelling
        return None

    def node(self, path):
        return None

    def createNode(self, type_name, name=None):  # noqa: N802 - HOM spelling
        return next(self._made)


def test_build_network_in_a_dop_network_names_it(monkeypatch, pop_source):
    popnet, dopnet, _ = pop_source
    made = MagicMock()
    made.path.return_value = "/obj/geo1/popnet/dopnet/popforce1"
    made.type.return_value.category.return_value = "Dop"
    made.parent.return_value = dopnet
    made.parm.return_value = None  # no Reset Simulation button of its own
    made.errors.return_value = []
    made.warnings.return_value = []
    node_type = MagicMock()
    node_type.name.return_value = "popforce"
    node_type.maxNumInputs.return_value = 4
    monkeypatch.setattr(hou, "node", lambda path: _DopParent(dopnet, [made]))
    monkeypatch.setattr(graph, "_resolve_node_type", lambda cat, name: node_type)
    monkeypatch.setattr(
        graph,
        "_parm_names_for_type",
        lambda scratch, resolved, **kwargs: (
            set(),
            set(),
            {},
            [],
            {"inputs": [], "outputs": []},
        ),
    )
    monkeypatch.setattr(graph, "place_new_nodes", lambda created: None)
    monkeypatch.setattr(graph, "layout_if_enabled", lambda parent: None)
    monkeypatch.setattr(graph, "_geometry_summary", lambda node: None)
    result = graph.build_network(dopnet.path(), [{"type": "popforce"}])
    assert result["success"] is True
    assert result["simulation_cache"]["networks"] == [popnet.path()]


class _WiredNode(_Node):
    """A _Node with readers (outputs() + dependents(), in one list) and a lock flag."""

    def __init__(self, path, category="Sop", parent=None, resimulate=False, locked=False):
        super().__init__(path, category=category, parent=parent, resimulate=resimulate)
        self._locked = locked
        self.readers: list = []

    def isInsideLockedHDA(self):  # noqa: N802
        return self._locked

    def outputs(self):
        siblings = self._path.rsplit("/", 1)[0]
        return [n for n in self.readers if n.path().rsplit("/", 1)[0] == siblings]

    def dependents(self):
        return [n for n in self.readers if n not in self.outputs()]


@pytest.fixture
def pop_scene():
    """/obj/pz/bx read by path by /obj/d/popsource1 (the POP Source's SOP Path)."""
    obj = _WiredNode("/obj", category="Manager")
    geo = _WiredNode("/obj/pz", category="Object", parent=obj)
    box = _WiredNode("/obj/pz/bx", parent=geo)
    dopnet = _WiredNode("/obj/d", category="Object", parent=obj, resimulate=True)
    source = _WiredNode("/obj/d/popsource1", category="Dop", parent=dopnet)
    box.readers = [source]
    return box, dopnet


class TestAnEditUpstreamOfASimulation:
    """A box a POP Source reads by path left frame 25 stale until a reset (22.0.429)."""

    def test_the_simulation_that_reads_it_is_named(self, pop_scene):
        box, dopnet = pop_scene
        note = dops.dop_cache_note([box])
        assert note["networks"] == [dopnet.path()]
        assert "upstream" in note["note"]

    def test_a_node_nothing_simulates_gets_no_note(self, pop_scene):
        box, _ = pop_scene
        box.readers = []
        assert dops.dop_cache_note([box]) is None

    def test_a_solver_inside_a_locked_asset_is_named_by_its_instance(self):
        # grid -> vellumconstraints -> vellumsolver; the constraints are read by
        # a DOP inside the solver asset, whose own dopnet has a reset button.
        geo = _WiredNode("/obj/vel", category="Object")
        grid = _WiredNode("/obj/vel/gr", parent=geo)
        constraints = _WiredNode("/obj/vel/vc", parent=geo)
        solver = _WiredNode("/obj/vel/vs", parent=geo, resimulate=True)
        inner = _WiredNode("/obj/vel/vs/dopnet1", parent=solver, resimulate=True, locked=True)
        source = _WiredNode("/obj/vel/vs/dopnet1/defaultsource", "Dop", parent=inner, locked=True)
        grid.readers = [constraints]
        constraints.readers = [solver, source]
        assert dops.dop_cache_note([grid])["networks"] == ["/obj/vel/vs"]

    def test_the_solver_itself_is_not_its_own_reason(self):
        # Its own parameters re-simulate (your check on timescale).
        solver = _WiredNode("/obj/vel/vs", resimulate=True)
        assert dops.dop_cache_note([solver]) is None

    def test_the_edited_nodes_own_insides_are_not_readers(self):
        hda = _WiredNode("/obj/geo/asset")
        dopnet = _WiredNode("/obj/geo/asset/dopnet", resimulate=True)
        hda.readers = [_WiredNode("/obj/geo/asset/dopnet/x", "Dop", parent=dopnet)]
        assert dops.dop_cache_note([hda]) is None

    def test_the_walk_stops_at_its_limit(self, pop_scene, monkeypatch):
        box, _ = pop_scene
        chain = [_WiredNode(f"/obj/pz/n{i}", parent=box.parent()) for i in range(5)]
        box.readers = [chain[0]]
        for a, b in zip(chain, chain[1:], strict=False):
            a.readers = [b]
        dopnet = _WiredNode("/obj/d", resimulate=True)
        chain[-1].readers = [_WiredNode("/obj/d/popsource1", "Dop", parent=dopnet)]
        monkeypatch.setattr(dops, "_DOWNSTREAM_LIMIT", 3)
        assert dops.dop_cache_note([box]) is None


class TestAnEditInsideASopSolver:
    """A SOP inside a SOP Solver DOP is inside the simulation too."""

    def test_its_dop_network_is_named(self):
        dopnet = _WiredNode("/obj/d2", category="Object", resimulate=True)
        solver = _WiredNode("/obj/d2/ss", category="Dop", parent=dopnet)
        shift = _WiredNode("/obj/d2/ss/shift", parent=solver)
        assert dops.dop_cache_note([shift])["networks"] == ["/obj/d2"]


class TestReviewFollowUps:
    def test_an_edit_inside_a_subnet_that_feeds_a_solver_is_named(self):
        # Measured on 22.0: subnet1/grid -> subnet1 -> vellumconstraints ->
        # vellumsolver had no note; the walk only followed wires out.
        geo = _WiredNode("/obj/vel", category="Object")
        subnet = _WiredNode("/obj/vel/subnet1", parent=geo)
        grid = _WiredNode("/obj/vel/subnet1/grid", parent=subnet)
        solver = _WiredNode("/obj/vel/vs", parent=geo, resimulate=True)
        subnet.displayNode = lambda: grid
        subnet.readers = [solver]
        assert dops.dop_cache_note([grid])["networks"] == [solver.path()]

    def test_a_simulation_in_an_asset_with_no_reset_promoted_keeps_its_network(self):
        obj = _WiredNode("/obj", category="Manager")
        asset = _WiredNode("/obj/studio_fx", category="Object", parent=obj)
        dopnet = _WiredNode(
            "/obj/studio_fx/dopnet1", category="Object", parent=asset, resimulate=True, locked=True
        )
        source = _WiredNode(
            "/obj/studio_fx/dopnet1/src", category="Dop", parent=dopnet, locked=True
        )
        assert dops.dop_cache_note([source])["networks"] == [dopnet.path()]


class TestARewiredSolver:
    """A Vellum Solver rewired from cloth A to cloth B still showed A at frame
    10 until a reset (22.0); connect_nodes said nothing, as the walk started
    downstream of the solver it had just wired."""

    def test_a_solver_whose_inputs_changed_is_named(self):
        solver = _WiredNode("/obj/vel/vs", resimulate=True)
        assert dops.dop_cache_note([solver]) is None  # its own parm: it resims
        assert dops.dop_cache_note([solver], rewired=True)["networks"] == [solver.path()]

    def test_a_rewired_node_outside_a_simulation_adds_nothing(self):
        assert dops.dop_cache_note([_WiredNode("/obj/geo1/merge1")], rewired=True) is None

    def test_every_wiring_tool_asks_with_rewired(self, monkeypatch):
        import inspect

        for handler in (
            nodes.connect_nodes,
            nodes.connect_nodes_batch,
            nodes.disconnect_node,
            nodes.reorder_inputs,
        ):
            assert "rewired=True" in inspect.getsource(handler), handler.__name__
