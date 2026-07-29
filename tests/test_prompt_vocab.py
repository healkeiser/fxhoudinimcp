"""The node names in the prompt markdown must be real, and correctly dated.

server_instructions.md has had a generated node section and a live accuracy test
for a while. The workflow prompts had neither, and it showed: usd_scene_assembly
advertised the LOP ``payload`` and ``karmashadowcatcher``, neither of which is a
node type, and simulation_setup advertised ``bulletsolver`` against a real
``bulletrbdsolver``. A later cleanup then swapped LOP ``instancer`` for
``copytopoints`` after checking a single 22.0 install, which silently removed the
only spelling 20.5 and 21.0 users have.

These tests read tools/node_versions.json, the accumulated evidence from every
sampled build, so they need no Houdini and run in CI. That file is also the right
authority rather than the newest install: a name can be correct for part of the
supported range and absent from the newest build.
"""

from __future__ import annotations

# Built-in
import json
import re
import sys
from pathlib import Path

# Third-party
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_MD_DIR = REPO_ROOT / "python" / "fxhoudinimcp" / "prompts" / "markdown" / "workflows"
_TOOLS = REPO_ROOT / "tools"

sys.path.insert(0, str(_TOOLS))

pytestmark = pytest.mark.skipif(
    not (_TOOLS / "node_versions.json").is_file(),
    reason="tools/node_versions.json absent; nothing to verify names against",
)

# Which context each prompt's node names belong to. A file listed here has its
# every node-shaped word checked, prose included, because the hand-written
# sentences around the generated tables name nodes too.
_FILE_CONTEXTS = {
    "model.md": ["Sop"],
    "copy.md": ["Sop"],
    "dyno.md": ["Sop", "Dop"],
    "pyro.md": ["Sop", "Dop"],
    "fluid.md": ["Sop", "Dop"],
    "vellum.md": ["Sop", "Dop"],
    "destruction.md": ["Sop", "Dop"],
    "mpm.md": ["Sop"],
    "grains.md": ["Sop", "Dop"],
    "ocean.md": ["Sop", "Dop"],
    "dopparticles.md": ["Sop", "Dop"],
    "finiteelements.md": ["Sop", "Dop"],
    "muscles.md": ["Sop", "Dop"],
    "crowds.md": ["Sop", "Dop"],
    "character.md": ["Sop"],
    "feathers.md": ["Sop"],
    "fur.md": ["Sop"],
    "heightfields.md": ["Sop"],
    "heightfields_cop.md": ["Cop"],
    "copernicus.md": ["Cop"],
    "composite.md": ["Cop2"],
    "solaris.md": ["Lop"],
    "tops.md": ["Top"],
    "assets.md": ["Sop"],
    "render.md": ["Driver"],
    "shade.md": ["Vop"],
    "props.md": ["Sop"],
    "io.md": ["Sop", "Driver"],
    "anim.md": ["Sop", "Chop"],
    "ml.md": ["Sop", "Top"],
    "troubleshooting.md": ["Sop", "Lop", "Dop"],
}


def test_every_prompt_markdown_is_covered():
    """No prompt file may sit outside the name audit.

    A new prompt is exactly when a batch of unverified node names arrives, so
    forgetting to register one defeats the whole check.
    """
    # Everything under workflows/ is served to a client, so everything under
    # workflows/ needs its names audited. shared/ and instructions/ are covered
    # elsewhere: server_instructions has a live accuracy test and a generated
    # node section, and shared/ names no nodes.
    shipped = {path.name for path in _MD_DIR.glob("*.md")}
    assert shipped == set(_FILE_CONTEXTS), (
        "prompt files not registered in _FILE_CONTEXTS: "
        f"{sorted(shipped - set(_FILE_CONTEXTS))}; stale entries: "
        f"{sorted(set(_FILE_CONTEXTS) - shipped)}"
    )


@pytest.fixture(scope="module")
def evidence():
    from gen_node_domains import deprecated_names
    from gen_node_versions import annotation_for, availability

    table = json.loads((_TOOLS / "node_versions.json").read_text(encoding="utf-8"))
    series, per_series = availability(table)

    def base_keys(context: str, name: str) -> list[str]:
        exact = f"{context}/{name}"
        if exact in per_series:
            return [exact]
        return sorted(k for k in per_series if k.startswith(f"{exact}::"))

    return {
        "series": series,
        "per_series": per_series,
        "deprecated": deprecated_names(table),
        "base_keys": base_keys,
        "annotation_for": annotation_for,
    }


# Words used as English in a file that are also node names in that context. The
# prose audit is a heuristic -- "any word that is also a node name is a node
# mention" -- and COPs breaks it, because SideFX named those nodes after the
# ordinary words: camera, cache, file, null, blur, switch, ramp. Listing the
# collisions per file keeps the check strict for names that are unambiguously
# node mentions, instead of forcing prose to avoid common English.
_ENGLISH_COLLISIONS = {
    "copernicus.md": {"camera", "cache"},
    "heightfields_cop.md": {"cache"},
    # Sop/camera is 22.0+, and these files use "camera" to mean the shot camera.
    "ocean.md": {"camera"},
    "props.md": {"camera"},
    "render.md": {"camera"},
}

# A backticked help citation like `pyro/lookdev` is a page path, not a claim that
# a node of that name exists. Auditing inside them flagged muscles/muscletransfer
# as an undated node mention when it is a page reference.
_CITATION = re.compile(r"`[a-z_]+/[a-z0-9_/]+`")


@pytest.fixture(scope="module")
def tool_names() -> set[str]:
    """MCP tool names, which look like node names and are not."""
    names: set[str] = set()
    for path in (REPO_ROOT / "python" / "fxhoudinimcp" / "tools").glob("*.py"):
        names |= set(re.findall(r"^async def (\w+)", path.read_text(encoding="utf-8"), re.M))
    return names


class TestCuratedVocabulary:
    """tools/prompt_vocab.json is hand-edited, so every name in it is a claim."""

    @pytest.fixture(scope="class")
    def vocab(self):
        return json.loads((_TOOLS / "prompt_vocab.json").read_text(encoding="utf-8"))

    def test_every_curated_name_exists(self, vocab, evidence):
        missing = []
        for block in vocab["blocks"]:
            for row in block["rows"]:
                for cell in row["cells"]:
                    for name in cell:
                        if not any(
                            evidence["base_keys"](context, name) for context in block["contexts"]
                        ):
                            missing.append(
                                f"{'/'.join(block['contexts'])}/{name} "
                                f"({block['file']}, row {row['label']})"
                            )
        assert not missing, "curated names no sampled build has: " + ", ".join(missing)

    def test_no_curated_name_is_deprecated(self, vocab, evidence):
        stale = []
        for block in vocab["blocks"]:
            for row in block["rows"]:
                for cell in row["cells"]:
                    for name in cell:
                        for context in block["contexts"]:
                            for key in evidence["base_keys"](context, name):
                                if key in evidence["deprecated"]:
                                    stale.append(f"{key} ({block['file']})")
        assert not stale, "curated names deprecated in the newest build: " + ", ".join(stale)

    def test_row_widths_match_headers(self, vocab):
        wrong = [
            f"{block['file']}/{block['marker']} row {row['label']}"
            for block in vocab["blocks"]
            for row in block["rows"]
            if len(row["cells"]) != len(block["headers"]) - 1
        ]
        assert not wrong, "rows whose cell count contradicts headers: " + ", ".join(wrong)


class TestGeneratedBlocksInSync:
    def test_markdown_matches_generator(self):
        """The committed markdown must be what the generator would write.

        Catches a hand-edit inside the markers, which is the failure mode the
        markers exist to prevent.
        """
        import gen_prompt_vocab

        assert gen_prompt_vocab.main.__module__  # imported, not executed
        argv = sys.argv
        sys.argv = ["gen_prompt_vocab.py", "--check"]
        try:
            code = gen_prompt_vocab.main()
        finally:
            sys.argv = argv
        assert code == 0, (
            "prompt markdown is stale or invalid; run python tools/gen_prompt_vocab.py"
        )


class TestHelpCitations:
    """The prompts tell the assistant to read specific shipped pages.

    A citation like `pyro/lookdev` is a promise that get_help_page will resolve
    it. SideFX moves and renames pages between releases, and a prompt that sends
    the model to a page that no longer exists teaches it the tool is unreliable.
    """

    @staticmethod
    def _help_root():
        try:
            from gen_node_domains import _newest_help_zip
        except Exception:
            return None
        found = _newest_help_zip()
        return found.parent if found else None

    def test_every_cited_page_exists(self):
        import zipfile

        root = self._help_root()
        if root is None:
            pytest.skip("no Houdini help found on this machine")

        def pages(scope: str):
            archive, directory = root / f"{scope}.zip", root / scope
            if archive.is_file():
                with zipfile.ZipFile(archive) as zf:
                    return {n[:-4] for n in zf.namelist() if n.endswith(".txt")}
            if directory.is_dir():
                return {p.relative_to(directory).as_posix()[:-4] for p in directory.rglob("*.txt")}
            return None

        broken = []
        for path in sorted(_MD_DIR.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"`([a-z_]+)/([a-z0-9_/]+)`", text):
                scope, page = match.group(1), match.group(2)
                available = pages(scope)
                if available is None:
                    # Not a help scope at all; the backticks are something else.
                    continue
                if page not in available:
                    broken.append(f"{path.name} cites {scope}/{page}")
        assert not broken, "citations that no longer resolve: " + ", ".join(broken)


class TestProseMentions:
    """Node names in hand-written prose are unverified by the generator.

    The tables are generated, but the sentences around them name nodes too
    ("fracturing -> voronoifracture"), and a version-limited name mentioned
    without a marker reads as available everywhere.
    """

    @pytest.mark.parametrize("filename", sorted(_FILE_CONTEXTS))
    def test_prose_names_exist_and_are_dated(self, filename, evidence, tool_names):
        text = _CITATION.sub(" ", (_MD_DIR / filename).read_text(encoding="utf-8"))
        contexts = _FILE_CONTEXTS[filename]
        undated = []

        for match in re.finditer(r"\b([a-z][a-z0-9_]{3,})\b(\s*\((\d+\.\d+[^)]*)\))?", text):
            name, annotation = match.group(1), match.group(3)
            if name in tool_names:
                continue
            if name in _ENGLISH_COLLISIONS.get(filename, ()):
                continue
            coverage = {}
            for context in contexts:
                for key in evidence["base_keys"](context, name):
                    coverage[key] = evidence["per_series"][key]
            if not coverage:
                continue  # an ordinary English word, not a node
            # Dated correctly if any spelling is present throughout, or if the
            # mention carries a marker.
            if annotation:
                continue
            if any(
                evidence["annotation_for"](per, evidence["series"]) is None
                for per in coverage.values()
            ):
                continue
            undated.append(f"{name} {sorted(coverage)}")

        assert not undated, (
            f"{filename} names nodes that do not exist across the whole "
            f"supported range without a version marker: {undated}"
        )
