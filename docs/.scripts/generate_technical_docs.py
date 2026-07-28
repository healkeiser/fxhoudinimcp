"""Generate the technical documentation pages."""

# Built-in
import logging
from pathlib import Path

# Third-party
import mkdocs_gen_files

log = logging.getLogger("mkdocs.plugins.gen-files")

nav = mkdocs_gen_files.Nav()
root = Path(__file__).parent.parent.parent
src = root / "python" / "fxhoudinimcp"

log.info("gen-files: Generating technical documentation...")

file_count = 0
skipped_count = 0

for path in sorted(src.rglob("*.py")):
    module_path = path.relative_to(root / "python")
    doc_path = path.relative_to(src).with_suffix(".md")
    full_doc_path = Path("technical", doc_path)

    parts = tuple(module_path.with_suffix("").parts)

    if parts[-1] == "__init__":
        parts = parts[:-1]
        if not parts:
            continue
        doc_path = doc_path.with_name("index.md")
        full_doc_path = full_doc_path.with_name("index.md")

    if parts[-1] == "__main__":
        skipped_count += 1
        continue

    nav_parts = tuple(part.lstrip("_") if part.startswith("_") else part for part in parts)

    nav[nav_parts] = doc_path.as_posix()

    with mkdocs_gen_files.open(full_doc_path, "w") as fd:
        ident = ".".join(parts)
        fd.write(f"::: {ident}")

    mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(root))
    log.info(f"gen-files: generated {full_doc_path.as_posix()}")
    file_count += 1

with mkdocs_gen_files.open("technical/SUMMARY.md", "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())

log.info(f"gen-files: Generated {file_count} documentation pages")
if skipped_count:
    log.debug(f"gen-files: Skipped {skipped_count} files (non-package directories)")
