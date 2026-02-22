"""HDA (Houdini Digital Asset) handlers for FXHoudini-MCP.

Provides tools for managing, inspecting, creating, and editing
Houdini Digital Assets.
"""

from __future__ import annotations

# Built-in
import os

# Third-party
import hou

# Internal
from fxhoudinimcp_server.dispatcher import register_handler


###### Helpers

def _get_node(node_path: str) -> hou.Node:
    """Return a node or raise if not found."""
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    return node


def _get_definition(node: hou.Node) -> hou.HDADefinition:
    """Return the HDA definition for a node or raise."""
    definition = node.type().definition()
    if definition is None:
        raise ValueError(
            f"Node {node.path()} is not an HDA instance. "
            f"Its type is '{node.type().name()}'."
        )
    return definition


def _definition_to_dict(definition: hou.HDADefinition) -> dict:
    """Convert an HDA definition to a plain dict."""
    info = {
        "type_name": definition.nodeTypeName(),
        "description": definition.description(),
        "icon": definition.icon(),
        "library_file": definition.libraryFilePath(),
    }

    try:
        info["version"] = definition.version()
    except Exception:
        info["version"] = None

    try:
        info["min_num_inputs"] = definition.minNumInputs()
        info["max_num_inputs"] = definition.maxNumInputs()
    except Exception:
        info["min_num_inputs"] = None
        info["max_num_inputs"] = None

    try:
        info["max_num_outputs"] = definition.maxNumOutputs()
    except Exception:
        info["max_num_outputs"] = None

    try:
        info["is_editable"] = not definition.isBlackBoxed()
    except Exception:
        info["is_editable"] = None

    try:
        info["embedded"] = definition.isEmbedded()
    except Exception:
        info["embedded"] = None

    # Section names
    try:
        info["sections"] = sorted(definition.sections().keys())
    except Exception:
        info["sections"] = []

    return info


def _parm_template_to_dict(pt) -> dict:
    """Convert a parm template to a plain dict."""
    info = {
        "name": pt.name(),
        "label": pt.label(),
        "type": str(pt.type()),
    }
    try:
        info["default_value"] = list(pt.defaultValue())
    except Exception:
        try:
            info["default_value"] = list(pt.defaultExpression())
        except Exception:
            info["default_value"] = None

    try:
        info["num_components"] = pt.numComponents()
    except Exception:
        info["num_components"] = 1

    try:
        info["is_hidden"] = pt.isHidden()
    except Exception:
        info["is_hidden"] = False

    return info


###### hda.list_installed_hdas

def list_installed_hdas(filter: str = None) -> dict:
    """List all installed HDA files and their definitions.

    Args:
        filter: Optional substring filter for HDA type names or file paths.
    """
    hda_files = hou.hda.loadedFiles()
    results = []

    for hda_file in hda_files:
        try:
            definitions = hou.hda.definitionsInFile(hda_file)
        except Exception:
            definitions = []

        for defn in definitions:
            type_name = defn.nodeTypeName()
            if filter and filter.lower() not in type_name.lower() and filter.lower() not in hda_file.lower():
                continue

            results.append({
                "type_name": type_name,
                "description": defn.description(),
                "library_file": hda_file,
                "version": defn.version() if hasattr(defn, "version") else None,
            })

    # Sort by type name
    results.sort(key=lambda x: x["type_name"])

    return {
        "hda_count": len(results),
        "hdas": results,
        "filter_applied": filter,
    }


###### hda.get_hda_info

def get_hda_info(
    node_path: str = None,
    hda_file: str = None,
    type_name: str = None,
) -> dict:
    """Return detailed information about an HDA definition.

    At least one of node_path, hda_file, or type_name must be provided.

    Args:
        node_path: Path to an HDA node instance.
        hda_file: Path to an HDA file on disk.
        type_name: Fully qualified HDA type name.
    """
    definition = None

    if node_path is not None:
        node = _get_node(node_path)
        definition = _get_definition(node)
    elif hda_file is not None:
        if not os.path.isfile(hda_file):
            raise FileNotFoundError(f"HDA file not found: {hda_file}")
        definitions = hou.hda.definitionsInFile(hda_file)
        if type_name:
            for defn in definitions:
                if defn.nodeTypeName() == type_name:
                    definition = defn
                    break
            if definition is None:
                raise ValueError(
                    f"Type '{type_name}' not found in {hda_file}. "
                    f"Available: {[d.nodeTypeName() for d in definitions]}"
                )
        elif definitions:
            definition = definitions[0]
        else:
            raise ValueError(f"No HDA definitions found in {hda_file}")
    elif type_name is not None:
        node_type = hou.nodeType(hou.sopNodeTypeCategory(), type_name)
        if node_type is None:
            # Try other categories
            for cat_func in [
                hou.objNodeTypeCategory,
                hou.lopNodeTypeCategory,
                hou.ropNodeTypeCategory,
                hou.cop2NodeTypeCategory,
                hou.topNodeTypeCategory,
                hou.dopNodeTypeCategory,
                hou.shopNodeTypeCategory,
                hou.vopNodeTypeCategory,
            ]:
                try:
                    node_type = hou.nodeType(cat_func(), type_name)
                    if node_type is not None:
                        break
                except Exception:
                    continue
        if node_type is None:
            raise ValueError(f"Node type not found: {type_name}")
        definition = node_type.definition()
        if definition is None:
            raise ValueError(f"Type '{type_name}' is not an HDA.")
    else:
        raise ValueError(
            "At least one of node_path, hda_file, or type_name must be provided."
        )

    info = _definition_to_dict(definition)

    # Parameter templates
    try:
        parm_templates = definition.parmTemplateGroup().entries()
        info["parameters"] = [_parm_template_to_dict(pt) for pt in parm_templates]
    except Exception:
        info["parameters"] = []

    # Input and output labels
    try:
        input_labels = []
        for i in range(definition.maxNumInputs()):
            try:
                label = definition.inputLabel(i)
                input_labels.append(label)
            except Exception:
                break
        info["input_labels"] = input_labels
    except Exception:
        info["input_labels"] = []

    try:
        output_labels = []
        for i in range(definition.maxNumOutputs()):
            try:
                label = definition.outputLabel(i)
                output_labels.append(label)
            except Exception:
                break
        info["output_labels"] = output_labels
    except Exception:
        info["output_labels"] = []

    return info


###### hda.install_hda

def install_hda(file_path: str, force: bool = False) -> dict:
    """Install an HDA file into the current Houdini session.

    Args:
        file_path: Path to the HDA file to install.
        force: If True, force reinstall even if already loaded.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"HDA file not found: {file_path}")

    # Check if already installed
    loaded_files = hou.hda.loadedFiles()
    already_loaded = any(
        os.path.normpath(f) == os.path.normpath(file_path) for f in loaded_files
    )

    if already_loaded and not force:
        return {
            "success": True,
            "file_path": file_path,
            "message": "HDA file is already installed.",
            "already_loaded": True,
        }

    try:
        hou.hda.installFile(file_path)
    except Exception as e:
        raise ValueError(f"Failed to install HDA: {e}")

    # List definitions that were installed
    definitions = hou.hda.definitionsInFile(file_path)
    type_names = [d.nodeTypeName() for d in definitions]

    return {
        "success": True,
        "file_path": file_path,
        "installed_types": type_names,
        "type_count": len(type_names),
    }


###### hda.uninstall_hda

def uninstall_hda(file_path: str) -> dict:
    """Uninstall an HDA file from the current Houdini session.

    Args:
        file_path: Path to the HDA file to uninstall.
    """
    try:
        hou.hda.uninstallFile(file_path)
    except Exception as e:
        raise ValueError(f"Failed to uninstall HDA: {e}")

    return {
        "success": True,
        "file_path": file_path,
        "message": "HDA file uninstalled.",
    }


###### hda.reload_hda

def reload_hda(file_path: str) -> dict:
    """Reload an HDA file from disk.

    Args:
        file_path: Path to the HDA file to reload.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"HDA file not found: {file_path}")

    try:
        hou.hda.reloadFile(file_path)
    except Exception as e:
        raise ValueError(f"Failed to reload HDA: {e}")

    definitions = hou.hda.definitionsInFile(file_path)
    type_names = [d.nodeTypeName() for d in definitions]

    return {
        "success": True,
        "file_path": file_path,
        "reloaded_types": type_names,
        "type_count": len(type_names),
    }


###### hda.create_hda

def create_hda(
    node_path: str,
    hda_file: str,
    type_name: str,
    label: str,
    version: str = "1.0",
) -> dict:
    """Create a new HDA from an existing subnet node.

    Args:
        node_path: Path to the subnet node to convert.
        hda_file: Destination file path for the HDA.
        type_name: The operator type name for the HDA.
        label: Human-readable label for the HDA.
        version: Version string (default "1.0").
    """
    node = _get_node(node_path)

    # Verify the node is a subnet
    if not node.isSubNetwork():
        raise ValueError(
            f"Node {node_path} is not a subnet. "
            "Only subnet nodes can be converted to HDAs."
        )

    try:
        hda_node = node.createDigitalAsset(
            name=type_name,
            hda_file_name=hda_file,
            description=label,
            version=version,
        )
    except Exception as e:
        raise ValueError(f"Failed to create HDA: {e}")

    return {
        "success": True,
        "node_path": hda_node.path(),
        "hda_file": hda_file,
        "type_name": type_name,
        "label": label,
        "version": version,
    }


###### hda.update_hda

def update_hda(node_path: str) -> dict:
    """Save the current node contents back to its HDA definition.

    Args:
        node_path: Path to the HDA node instance.
    """
    node = _get_node(node_path)
    definition = _get_definition(node)

    try:
        node.type().definition().updateFromNode(node)
    except Exception as e:
        raise ValueError(f"Failed to update HDA definition: {e}")

    return {
        "success": True,
        "node_path": node.path(),
        "type_name": definition.nodeTypeName(),
        "library_file": definition.libraryFilePath(),
        "message": "HDA definition updated from node contents.",
    }


###### hda.get_hda_sections

def get_hda_sections(node_path: str) -> dict:
    """List all sections in an HDA definition.

    Sections include DialogScript, PythonModule, Help, ExtraFileOptions, etc.

    Args:
        node_path: Path to an HDA node instance.
    """
    node = _get_node(node_path)
    definition = _get_definition(node)

    sections = definition.sections()
    section_info = []

    for name, section in sorted(sections.items()):
        info = {"name": name}
        try:
            content = section.contents()
            info["size_bytes"] = len(content) if content else 0
        except Exception:
            info["size_bytes"] = None
        section_info.append(info)

    return {
        "node_path": node.path(),
        "type_name": definition.nodeTypeName(),
        "section_count": len(section_info),
        "sections": section_info,
    }


###### hda.get_hda_section_content

def get_hda_section_content(node_path: str, section_name: str) -> dict:
    """Read the content of a specific section in an HDA definition.

    Args:
        node_path: Path to an HDA node instance.
        section_name: Name of the section to read (e.g. "PythonModule", "Help").
    """
    node = _get_node(node_path)
    definition = _get_definition(node)

    sections = definition.sections()
    if section_name not in sections:
        available = sorted(sections.keys())
        raise ValueError(
            f"Section '{section_name}' not found in HDA '{definition.nodeTypeName()}'. "
            f"Available sections: {available}"
        )

    try:
        content = sections[section_name].contents()
    except Exception as e:
        raise ValueError(f"Failed to read section '{section_name}': {e}")

    return {
        "node_path": node.path(),
        "type_name": definition.nodeTypeName(),
        "section_name": section_name,
        "content": content,
        "size_bytes": len(content) if content else 0,
    }


###### hda.set_hda_section_content

def set_hda_section_content(
    node_path: str,
    section_name: str,
    content: str,
) -> dict:
    """Write content to a specific section in an HDA definition.

    Creates the section if it does not exist.

    Args:
        node_path: Path to an HDA node instance.
        section_name: Name of the section to write (e.g. "PythonModule", "Help").
        content: The content to write to the section.
    """
    node = _get_node(node_path)
    definition = _get_definition(node)

    try:
        definition.addSection(section_name, content)
    except Exception as e:
        raise ValueError(f"Failed to write section '{section_name}': {e}")

    return {
        "success": True,
        "node_path": node.path(),
        "type_name": definition.nodeTypeName(),
        "section_name": section_name,
        "size_bytes": len(content) if content else 0,
        "message": f"Section '{section_name}' updated.",
    }


###### Registration

register_handler("hda.list_installed_hdas", list_installed_hdas)
register_handler("hda.get_hda_info", get_hda_info)
register_handler("hda.install_hda", install_hda)
register_handler("hda.uninstall_hda", uninstall_hda)
register_handler("hda.reload_hda", reload_hda)
register_handler("hda.create_hda", create_hda)
register_handler("hda.update_hda", update_hda)
register_handler("hda.get_hda_sections", get_hda_sections)
register_handler("hda.get_hda_section_content", get_hda_section_content)
register_handler("hda.set_hda_section_content", set_hda_section_content)
