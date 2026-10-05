"""get_node_card had no connector list, and build_network wired by index only.

The card reported min/max input counts and nothing else about the connectors,
so the index of `texcoord` on mtlximage (3) could not be read anywhere; and a
build_network spec could name an input only by index, while connect_nodes had
taken an input_name for months. The card now lists `inputs` / `outputs` with
index, name and label, probed on a throwaway instance (hou.NodeType has no
inputNames), and build_network resolves `input_name` at dry-run time with a
did-you-mean over names and labels.

hou is mocked here; the live check ran on Houdini 22.0.429.
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
import fxhoudinimcp_server.handlers.graph_handlers as graph  # noqa: E402
import fxhoudinimcp_server.handlers.node_handlers as nodes  # noqa: E402

hou = graph.hou


def _probe(inputs, labels, outputs=("output1",), data_types=()):
    probe = MagicMock()
    probe.inputNames.return_value = list(inputs)
    probe.inputLabels.return_value = list(labels)
    probe.inputDataTypes.return_value = list(data_types)
    probe.outputNames.return_value = list(outputs)
    probe.outputLabels.return_value = [o.title() for o in outputs]
    probe.parms.return_value = []
    probe.parmTuples.return_value = []
    return probe


class TestConnectorsOfANode:
    def test_index_name_label_and_data_type_are_reported(self):
        probe = _probe(
            ["file", "layer", "default", "texcoord"],
            ["Filename", "Layer", "Default Color", "Texture Coordinates"],
            outputs=["out"],
            data_types=["ustring", "ustring", "color", "vector2"],
        )
        connectors = graph._connectors_of(probe)
        assert connectors["inputs"][3] == {
            "index": 3,
            "name": "texcoord",
            "label": "Texture Coordinates",
            "data_type": "vector2",
        }
        assert connectors["outputs"] == [{"index": 0, "name": "out", "label": "Out"}]

    def test_a_node_without_data_types_still_lists_its_inputs(self):
        probe = _probe(["input1", "input2"], ["Geometry for operation", "Spine curve"])
        probe.inputDataTypes.side_effect = AttributeError("SOPs have none")
        inputs = graph._connectors_of(probe)["inputs"]
        assert [i["label"] for i in inputs] == ["Geometry for operation", "Spine curve"]
        assert "data_type" not in inputs[0]

    def test_one_failing_read_does_not_lose_the_others(self):
        probe = _probe(["input1", "input2"], [])
        probe.inputLabels.side_effect = RuntimeError("labels unavailable")
        inputs = graph._connectors_of(probe)["inputs"]
        assert [i["name"] for i in inputs] == ["input1", "input2"]

    def test_outputs_carry_their_data_type_too(self):
        # Whether a multiply comes out float or int was answerable for its
        # inputs only.
        probe = _probe(["input1"], ["Input 1"], outputs=["product"])
        probe.outputDataTypes.return_value = ("float",)
        assert graph._connectors_of(probe)["outputs"] == [
            {"index": 0, "name": "product", "label": "Product", "data_type": "float"}
        ]

    def test_outputs_without_data_types_are_still_listed(self):
        probe = _probe([], [], outputs=["output1"])
        probe.outputDataTypes.side_effect = AttributeError("SOPs have none")
        assert graph._connectors_of(probe)["outputs"] == [
            {"index": 0, "name": "output1", "label": "Output1"}
        ]


class TestFindingAnInput:
    """One rule for the dry run and for every wiring verb (node_handlers)."""

    TABLE = [
        {"index": 0, "name": "input1", "label": "Geometry for operation"},
        {"index": 1, "name": "input2", "label": "Spine curve"},
    ]

    def test_a_name_or_a_label_resolves_to_the_index(self):
        assert nodes._find_input(self.TABLE, "input2") == 1
        assert nodes._find_input(self.TABLE, "Spine curve") == 1
        with pytest.raises(ValueError, match="no input named 'spine'"):
            nodes._find_input(self.TABLE, "spine")

    def test_names_win_over_labels(self):
        table = [
            {"index": 0, "name": "a", "label": "b"},
            {"index": 1, "name": "b", "label": "c"},
        ]
        assert nodes._find_input(table, "b") == 1

    def test_a_variadic_series_continues_past_what_a_fresh_node_shows(self):
        table = [{"index": 0, "name": "input1", "label": "Input 1"}]
        assert nodes._find_input(table, "input3", max_inputs=9999) == 2
        with pytest.raises(ValueError):
            nodes._find_input(table, "input3", max_inputs=1)
        with pytest.raises(ValueError):
            nodes._find_input(table, "other3", max_inputs=9999)

    def test_the_hint_is_close_matches_or_a_capped_deduplicated_list(self):
        table = [{"index": i, "name": f"in{i}", "label": f"in{i}"} for i in range(40)]
        with pytest.raises(ValueError) as close:
            nodes._find_input(table, "in_3")
        assert "Did you mean" in str(close.value)
        with pytest.raises(ValueError) as listed:
            nodes._find_input(table, "zzz")
        assert str(listed.value).count("'in") == 15 and "..." in str(listed.value)


class TestProbingAType:
    @pytest.fixture(autouse=True)
    def _fresh(self, monkeypatch):
        monkeypatch.setattr(graph, "_CONNECTOR_CACHE", {})
        monkeypatch.setattr(graph, "_definition_stamp", lambda node_type: None)

    def _root(self, monkeypatch, probe):
        root = MagicMock()
        scratch = MagicMock()
        root.createNode.return_value = scratch
        scratch.createNode.return_value = probe
        monkeypatch.setattr(hou, "node", lambda path: root)
        monkeypatch.setattr(graph, "_container_for", lambda category: "geo")
        return root, scratch

    def test_no_container_for_the_category_is_said_not_hidden(self, monkeypatch):
        node = MagicMock()
        monkeypatch.setattr(hou, "node", node)
        monkeypatch.setattr(graph, "_container_for", lambda category: None)
        connectors, why = graph._connectors_for_type("Shop", MagicMock())
        assert connectors is None and "Shop" in why
        node.assert_not_called()

    def test_the_probe_runs_without_creation_scripts_and_is_destroyed(self, monkeypatch):
        root, scratch = self._root(monkeypatch, _probe(["input1"], ["Input 1"]))
        node_type = MagicMock()
        node_type.name.return_value = "polyextrude::2.0"

        connectors, why = graph._connectors_for_type("Sop", node_type)

        root.createNode.assert_called_once_with("geo", "fxhoudinimcp_card_probe")
        scratch.createNode.assert_called_once_with("polyextrude::2.0", run_init_scripts=False)
        assert connectors["inputs"] == [{"index": 0, "name": "input1", "label": "Input 1"}]
        assert why is None
        scratch.destroy.assert_called_once()

    def test_a_second_card_for_the_type_does_not_probe_again(self, monkeypatch):
        root, _ = self._root(monkeypatch, _probe(["input1"], ["Input 1"]))
        node_type = MagicMock()
        node_type.name.return_value = "blast"
        graph._connectors_for_type("Sop", node_type)
        graph._connectors_for_type("Sop", node_type)
        root.createNode.assert_called_once()

    def test_a_failed_probe_says_why_and_still_cleans_up(self, monkeypatch):
        _, scratch = self._root(monkeypatch, None)
        scratch.createNode.side_effect = RuntimeError("no license for this type")
        connectors, why = graph._connectors_for_type("Sop", MagicMock())
        assert connectors is None and "no license" in why
        scratch.destroy.assert_called_once()

    def _refusing_matnet(self, monkeypatch, probe):
        """A material network that refuses the type, then a geo that takes it."""
        root = MagicMock()
        matnet, geo, attribvop = MagicMock(), MagicMock(), MagicMock()
        matnet.createNode.side_effect = RuntimeError("Error in child VOP 'P'.")
        geo.createNode.return_value = attribvop
        attribvop.createNode.return_value = probe
        root.createNode.side_effect = lambda type_name, name: {"matnet": matnet, "geo": geo}[
            type_name
        ]
        monkeypatch.setattr(hou, "node", lambda path: root)
        monkeypatch.setattr(graph, "_container_for", lambda category: "matnet")
        return root, matnet, geo, attribvop

    def test_a_vop_a_material_network_refuses_is_probed_in_an_attribute_vop(self, monkeypatch):
        # geometryvopglobal::2.0 fails to match its definition inside a
        # matnet; inside an Attribute VOP it builds, with its 22 outputs.
        probe = _probe([], [], outputs=["P", "v"])
        root, matnet, geo, attribvop = self._refusing_matnet(monkeypatch, probe)
        node_type = MagicMock()
        node_type.name.return_value = "geometryvopglobal::2.0"

        connectors, why = graph._connectors_for_type("Vop", node_type)

        assert why is None
        assert [o["name"] for o in connectors["outputs"]] == ["P", "v"]
        assert [c.args[0] for c in root.createNode.call_args_list] == ["matnet", "geo"]
        geo.createNode.assert_called_once_with("attribvop")
        attribvop.createNode.assert_called_once_with(
            "geometryvopglobal::2.0", run_init_scripts=False
        )
        matnet.destroy.assert_called_once()
        geo.destroy.assert_called_once()

    def test_when_both_refuse_the_first_reason_is_reported(self, monkeypatch):
        root, matnet, geo, attribvop = self._refusing_matnet(monkeypatch, None)
        attribvop.createNode.side_effect = RuntimeError("not in an attribvop either")
        connectors, why = graph._connectors_for_type("Vop", MagicMock())
        assert connectors is None
        assert "Error in child VOP 'P'" in why and "attribvop" not in why
        matnet.destroy.assert_called_once()
        geo.destroy.assert_called_once()

    def test_other_categories_have_no_second_container(self, monkeypatch):
        root, scratch = self._root(monkeypatch, None)
        scratch.createNode.side_effect = RuntimeError("no license for this type")
        graph._connectors_for_type("Sop", MagicMock())
        root.createNode.assert_called_once()

    def test_a_container_is_found_by_child_category_when_not_preferred(self, monkeypatch):
        def obj_type(child, hidden=False):
            node_type = MagicMock()
            node_type.childTypeCategory.return_value.name.return_value = child
            node_type.hidden.return_value = hidden
            return node_type

        category = MagicMock()
        category.nodeTypes.return_value = {
            "cop2net": obj_type("Cop2", hidden=True),
            "geo": obj_type("Sop"),
            "shopnet": obj_type("Shop"),
        }
        monkeypatch.setattr(hou, "objNodeTypeCategory", lambda: category)
        assert graph._container_for("Shop") == "shopnet"
        assert graph._container_for("Cop2") == "cop2net"
        assert graph._container_for("Sop") == "geo"
        assert graph._container_for("Nothing") is None

    def test_the_parm_probe_returns_connectors_as_a_fifth_element(self, monkeypatch):
        scratch = MagicMock()
        scratch.createNode.return_value = _probe(["input1"], ["Input 1"])
        monkeypatch.setattr(graph, "_instance_patterns", lambda t: [])
        *_, connectors = graph._parm_names_for_type(scratch, MagicMock())
        assert connectors["inputs"] == [{"index": 0, "name": "input1", "label": "Input 1"}]


class _VopNode(MagicMock):
    """Stands in for hou.VopNode, so isinstance() can tell a VOP from a SOP."""


class TestNodeInfoNamesALiveVopsConnectorTypes:
    """A variadic VOP input is "undef" on the type and float or int once wired.

    The card can only show the type; whether a wired multiply comes out float
    is a question about the live node, which HOM answers with
    inputDataTypes() / outputDataTypes() and no verb returned.
    """

    @pytest.fixture(autouse=True)
    def _vop(self, monkeypatch):
        monkeypatch.setattr(hou, "VopNode", _VopNode, raising=False)
        monkeypatch.setattr(nodes, "to_jsonable", lambda v: v)

    def _info(self, monkeypatch, node):
        monkeypatch.setattr(nodes, "_get_node", lambda path: node)
        return nodes.get_node_info("/obj/geo1/attribvop1/multiply1")

    def test_a_vop_reports_what_its_connectors_carry(self, monkeypatch):
        node = _VopNode()
        node.inputNames.return_value = ("input1", "input2")
        node.inputDataTypes.return_value = ("float", "float")
        node.outputNames.return_value = ("product",)
        node.outputDataTypes.return_value = ("float",)
        info = self._info(monkeypatch, node)
        assert info["connector_types"] == {
            "inputs": {"input1": "float", "input2": "float"},
            "outputs": {"product": "float"},
        }

    def test_a_sop_has_none(self, monkeypatch):
        assert "connector_types" not in self._info(monkeypatch, MagicMock())


class TestBuildNetworkWiresByName:
    def _network(self, monkeypatch, input_names, input_labels):
        parent = MagicMock()
        parent.path.return_value = "/obj/mat1"
        parent.children.return_value = []
        parent.displayNode.return_value = None
        parent.renderNode.return_value = None
        category = MagicMock()
        category.name.return_value = "Vop"
        parent.childTypeCategory.return_value = category
        srf_type = MagicMock()
        srf_type.name.return_value = "mtlxstandard_surface"
        srf_type.maxNumInputs.return_value = len(input_names)
        img_type = MagicMock()
        img_type.name.return_value = "mtlximage"
        img_type.maxNumInputs.return_value = 0
        types = {"mtlxstandard_surface": srf_type, "mtlximage": img_type}
        self.probes = []

        def create(type_name, *args, **kwargs):
            probe = _probe(input_names, input_labels)
            self.probes.append(probe)
            return probe

        parent.createNode.side_effect = create
        monkeypatch.setattr(hou, "node", lambda path: parent if path == "/obj/mat1" else None)
        monkeypatch.setattr(graph, "_resolve_node_type", lambda cat, name: types.get(name))
        monkeypatch.setattr(graph, "_instance_patterns", lambda t: [])
        return parent

    def test_a_wrong_name_fails_the_dry_run_with_a_hint(self, monkeypatch):
        self._network(monkeypatch, ["base_color", "sheen_color"], ["Base Color", "Sheen Color"])
        result = graph.build_network(
            "/obj/mat1",
            [
                {"type": "mtlximage", "name": "img"},
                {
                    "type": "mtlxstandard_surface",
                    "name": "srf",
                    "inputs": [{"source": "img", "input_name": "base_colour"}],
                },
            ],
            dry_run=True,
        )
        assert result["valid"] is False
        assert "no input named 'base_colour'" in result["errors"][0]
        assert "base_color" in result["errors"][0]

    def test_a_known_name_validates(self, monkeypatch):
        self._network(monkeypatch, ["base_color", "sheen_color"], ["Base Color", "Sheen Color"])
        result = graph.build_network(
            "/obj/mat1",
            [
                {"type": "mtlximage", "name": "img"},
                {
                    "type": "mtlxstandard_surface",
                    "name": "srf",
                    "inputs": [{"source": "img", "input_name": "Sheen Color"}],
                },
            ],
            dry_run=True,
        )
        assert result["valid"] is True, result

    def test_an_index_past_the_connectors_is_still_refused(self, monkeypatch):
        self._network(monkeypatch, ["base_color"], ["Base Color"])
        result = graph.build_network(
            "/obj/mat1",
            [
                {"type": "mtlximage", "name": "img"},
                {
                    "type": "mtlxstandard_surface",
                    "name": "srf",
                    "inputs": [{"source": "img", "index": 5}],
                },
            ],
            dry_run=True,
        )
        assert result["valid"] is False
        assert "exceeds max inputs" in result["errors"][0]

    def test_the_spec_s_own_parms_decide_its_connectors(self, monkeypatch):
        parent = self._network(monkeypatch, ["in1", "in2"], ["In 1", "In 2"])
        switch_type = MagicMock()
        switch_type.name.return_value = "mtlxswitch"
        switch_type.maxNumInputs.return_value = 10
        img_type = MagicMock()
        img_type.name.return_value = "mtlximage"
        img_type.maxNumInputs.return_value = 0
        types = {"mtlxswitch": switch_type, "mtlximage": img_type}
        monkeypatch.setattr(graph, "_resolve_node_type", lambda cat, name: types.get(name))
        signature = MagicMock()
        signature.name.return_value = "signature"
        default = _probe(["bg", "fg"], ["Background", "Foreground"])
        default.parms.return_value = [signature]
        configured = _probe(["bg", "fg", "mix"], ["Background", "Foreground", "Mix"])
        # mtlximage probe, mtlxswitch probe at defaults, then the switch again
        # with the spec's parms applied.
        made = iter([_probe([], []), default, configured])
        parent.createNode.side_effect = lambda *a, **k: next(made)
        monkeypatch.setattr(graph, "_apply_parm", lambda node, name, value: None)
        result = graph.build_network(
            "/obj/mat1",
            [
                {"type": "mtlximage", "name": "img"},
                {
                    "type": "mtlxswitch",
                    "name": "sw",
                    "parms": {"signature": "color3"},
                    "inputs": [{"source": "img", "input_name": "mix"}],
                },
            ],
            dry_run=True,
        )
        assert result["valid"] is True, result

    def test_an_unresolved_type_reports_one_error_not_two(self, monkeypatch):
        self._network(monkeypatch, ["base_color"], ["Base Color"])
        result = graph.build_network(
            "/obj/mat1",
            [
                {"type": "mtlximage", "name": "img"},
                {
                    "type": "mtlxstandard_surfce",
                    "name": "srf",
                    "inputs": [{"source": "img", "input_name": "base_color"}],
                },
            ],
            dry_run=True,
        )
        assert result["valid"] is False
        assert len(result["errors"]) == 1, result["errors"]

    def test_a_bad_name_and_a_bad_source_are_reported_in_one_pass(self, monkeypatch):
        self._network(monkeypatch, ["base_color"], ["Base Color"])
        result = graph.build_network(
            "/obj/mat1",
            [
                {"type": "mtlximage", "name": "img"},
                {
                    "type": "mtlxstandard_surface",
                    "name": "srf",
                    "inputs": [{"source": "imge", "input_name": "base_colour"}],
                },
            ],
            dry_run=True,
        )
        joined = " | ".join(result["errors"])
        assert "no input named 'base_colour'" in joined and "'imge'" in joined

    def test_a_merge_takes_a_later_input_by_name(self, monkeypatch):
        self._network(monkeypatch, ["input1"], ["Input 1"])
        merge_type = MagicMock()
        merge_type.name.return_value = "merge"
        merge_type.maxNumInputs.return_value = 9999
        img_type = MagicMock()
        img_type.name.return_value = "mtlximage"
        img_type.maxNumInputs.return_value = 0
        types = {"merge": merge_type, "mtlximage": img_type}
        monkeypatch.setattr(graph, "_resolve_node_type", lambda cat, name: types.get(name))
        result = graph.build_network(
            "/obj/mat1",
            [
                {"type": "mtlximage", "name": "a"},
                {"type": "mtlximage", "name": "b"},
                {
                    "type": "merge",
                    "name": "m",
                    "inputs": [
                        {"source": "a", "input_name": "input1"},
                        {"source": "b", "input_name": "input2"},
                    ],
                },
            ],
            dry_run=True,
        )
        assert result["valid"] is True, result


class TestFindingAnOutput:
    """source_output took an index only: "v" died on int() with "invalid literal"."""

    OUTPUTS = [
        {"index": 0, "name": "P", "label": "Position"},
        {"index": 1, "name": "v", "label": "Velocity"},
        {"index": 11, "name": "Frame", "label": "Frame"},
    ]

    def test_a_name_or_a_label_resolves_to_the_index(self):
        assert nodes._find_output(self.OUTPUTS, "v") == 1
        assert nodes._find_output(self.OUTPUTS, "Velocity") == 1
        assert nodes._find_output(self.OUTPUTS, "Frame") == 11

    def test_a_typo_names_the_outputs(self):
        with pytest.raises(
            ValueError, match=r"no output named 'Positon'.*Did you mean.*'Position'"
        ):
            nodes._find_output(self.OUTPUTS, "Positon")
        with pytest.raises(
            ValueError, match=r"Outputs: \['P', 'Position', 'v', 'Velocity', 'Frame'\]"
        ):
            nodes._find_output(self.OUTPUTS, "zzz")

    def test_the_live_source_resolves_the_name_at_wiring(self):
        source = _probe([], [], outputs=["P", "v"])
        source.path.return_value = "/obj/geo1/attribvop1/geometryvopglobal1"
        assert nodes._output_index(source, "v") == 1
        assert nodes._output_index(source, "V") == 1  # the label, title-cased by _probe
        assert nodes._output_index(source, 0) == 0
        with pytest.raises(ValueError, match="geometryvopglobal1 has no output named 'vel'"):
            nodes._output_index(source, "vel")

    def test_an_entry_keeps_a_name_and_reads_a_digit_string_as_an_index(self):
        assert (
            graph._parse_input_entry({"source": "g", "source_output": "v"}, 0)["source_output"]
            == "v"
        )
        assert (
            graph._parse_input_entry({"source": "g", "source_output": "2"}, 0)["source_output"] == 2
        )
        assert graph._parse_input_entry({"source": "g"}, 0)["source_output"] == 0
        with pytest.raises(ValueError, match="output index or name"):
            graph._parse_input_entry({"source": "g", "source_output": True}, 0)

    def test_a_whole_float_is_still_an_index(self):
        # int() took 1.0 before names were accepted; it must not become the name "1.0".
        assert (
            graph._parse_input_entry({"source": "g", "source_output": 1.0}, 0)["source_output"] == 1
        )


class TestBuildNetworkWiresFromAnOutputByName:
    def _network(self, monkeypatch, children=()):
        parent = MagicMock()
        parent.path.return_value = "/obj/geo1/attribvop1"
        parent.children.return_value = list(children)
        parent.node.side_effect = lambda name: next(
            (child for child in children if child.name() == name), None
        )
        parent.displayNode.return_value = None
        parent.renderNode.return_value = None
        category = MagicMock()
        category.name.return_value = "Vop"
        parent.childTypeCategory.return_value = category
        types = {}
        for name, max_inputs in (("globals", 0), ("vectofloat", 1)):
            types[name] = MagicMock()
            types[name].name.return_value = name
            types[name].maxNumInputs.return_value = max_inputs
        probes = {
            "globals": lambda: _probe([], [], outputs=["P", "v"]),
            "vectofloat": lambda: _probe(["vec"], ["Vector"], outputs=["fval1"]),
        }
        parent.createNode.side_effect = lambda type_name, *a, **k: probes[type_name]()
        monkeypatch.setattr(hou, "node", lambda path: parent if path == parent.path() else None)
        monkeypatch.setattr(graph, "_resolve_node_type", lambda cat, name: types.get(name))
        monkeypatch.setattr(graph, "_instance_patterns", lambda t: [])
        return parent

    def _spec(self, source, source_output):
        return {
            "type": "vectofloat",
            "name": "split",
            "inputs": [{"input_name": "vec", "source": source, "source_output": source_output}],
        }

    def test_an_output_name_of_a_spec_node_validates(self, monkeypatch):
        self._network(monkeypatch)
        result = graph.build_network(
            "/obj/geo1/attribvop1",
            [{"type": "globals", "name": "g"}, self._spec("g", "v")],
            dry_run=True,
        )
        assert result["valid"] is True, result

    def test_a_wrong_output_name_fails_the_dry_run_with_a_hint(self, monkeypatch):
        self._network(monkeypatch)
        result = graph.build_network(
            "/obj/geo1/attribvop1",
            [{"type": "globals", "name": "g"}, self._spec("g", "vel")],
            dry_run=True,
        )
        assert result["valid"] is False
        assert len(result["errors"]) == 1, result["errors"]
        assert "input source 'g' has no output named 'vel'" in result["errors"][0]
        assert "Did you mean: ['v']" in result["errors"][0]

    def test_an_existing_child_is_checked_on_its_own_outputs(self, monkeypatch):
        live = _probe([], [], outputs=["P", "v"])
        live.name.return_value = "geometryvopglobal1"
        self._network(monkeypatch, children=[live])
        ok = graph.build_network(
            "/obj/geo1/attribvop1", [self._spec("geometryvopglobal1", "v")], dry_run=True
        )
        assert ok["valid"] is True, ok
        typo = graph.build_network(
            "/obj/geo1/attribvop1", [self._spec("geometryvopglobal1", "vel")], dry_run=True
        )
        assert "no output named 'vel'" in typo["errors"][0]

    def test_the_build_wires_the_named_output(self, monkeypatch):
        live = _probe([], [], outputs=["P", "v"])
        live.name.return_value = "geometryvopglobal1"
        parent = self._network(monkeypatch, children=[live])
        built = _probe(["vec"], ["Vector"], outputs=["fval1"])
        built.path.return_value = "/obj/geo1/attribvop1/split"
        make = parent.createNode.side_effect
        parent.createNode.side_effect = lambda type_name, name=None, *a, **k: (
            built if name == "split" else make(type_name)
        )
        monkeypatch.setattr(graph, "place_new_nodes", lambda nodes: None)
        result = graph.build_network(
            "/obj/geo1/attribvop1", [self._spec("geometryvopglobal1", "v")]
        )
        assert result["success"] is True, result
        built.setInput.assert_called_once_with(0, live, 1)
