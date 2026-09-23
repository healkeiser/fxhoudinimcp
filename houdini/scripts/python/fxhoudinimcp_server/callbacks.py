"""Pressing a parameter the way a click does, without Houdini's error dialog.

``hou.Parm.pressButton()`` runs a parameter's callback script. In a graphical
session a PYTHON callback that raises is answered with Houdini's modal "Error
running callback" window, and Houdini's main thread -- which every command of
this bridge runs on -- waits for someone to click OK. Measured on 22.0.429:
the command that pressed returned, the next one timed out after 120 s, and
Houdini had to be killed. The dialog's "Send Future Errors to the Console"
choice is not reachable from HOM: no preference and no environment variable
sets it.

What was measured per route, in a GUI session:

* no callback script -- a built-in C++ action (a ROP's Render, a File's
  Reload, Stash Input): no such dialog; ``pressButton()`` it is.
* HScript callback -- a failing command is reported nowhere and opens no
  window; ``pressButton()`` returned and the next command answered in 0.3 s.
* Python callback -- the dialog. So the script is executed here instead, with
  what ``pressButton()`` hands it (measured): globals ``hou`` and ``kwargs``;
  kwargs ``node``, ``parm``, ``parm_name``, ``script_parm``, ``script_value``,
  ``script_value0`` and ``script_multiparm_index`` / ``_nesting`` as strings
  ('-1', '0'), with the caller's arguments merged in; ``hou.pwd()`` is the
  node while it runs. Its exception comes back as CallbackError.
"""

from __future__ import annotations

# Built-in
import builtins
import contextlib
import traceback
from typing import Any

# Third-party
import hou


class CallbackError(RuntimeError):
    """A parameter's Python callback raised; the message carries its traceback tail."""


def callback_script(parm: hou.Parm) -> str:
    """The parm's callback script; "" when it has none (a built-in action)."""
    with contextlib.suppress(Exception):
        script = parm.parmTemplate().scriptCallback()
        if isinstance(script, str):
            return script
    return ""


def _is_python(parm: hou.Parm) -> bool:
    with contextlib.suppress(Exception):
        return parm.parmTemplate().scriptCallbackLanguage() == hou.scriptLanguage.Python
    return False


def _callback_kwargs(parm: hou.Parm, arguments: dict | None) -> dict[str, Any]:
    """The kwargs pressButton() gives a Python callback (measured on 22.0.429)."""
    index, nesting = "-1", "0"
    with contextlib.suppress(Exception):
        indices = parm.multiParmInstanceIndices()
        if indices:
            index, nesting = str(indices[-1]), str(len(indices))
    kwargs: dict[str, Any] = {
        "node": parm.node(),
        "parm": parm,
        "parm_name": parm.name(),
        "script_parm": parm.name(),
        "script_multiparm_index": index,
        "script_multiparm_nesting": nesting,
    }
    value = ""
    with contextlib.suppress(Exception):
        value = parm.evalAsString()
    kwargs["script_value"] = kwargs["script_value0"] = value
    with contextlib.suppress(Exception):
        components = list(parm.tuple())
        if len(components) > 1:
            for i, component in enumerate(components):
                kwargs[f"script_value{i}"] = component.evalAsString()
    kwargs.update(arguments or {})
    return kwargs


def _script_name(parm: hou.Parm) -> str:
    """What Houdini names the script in a traceback: `Lop/karmarendersettings/res_mode`."""
    with contextlib.suppress(Exception):
        return f"{parm.node().type().nameWithCategory()}/{parm.name()}"
    return parm.name()


def exec_python_callback(parm: hou.Parm, script: str, kwargs: dict[str, Any]) -> None:
    """Execute *script* as pressButton() would; raise CallbackError if it raises."""
    node = parm.node()
    previous = hou.pwd()
    hou.setPwd(node)
    try:
        with hou.undos.group(f"Callback {node.path()}/{parm.name()}"):
            exec(  # noqa: S102 -- the node's own callback, which a click would run too
                compile(script, _script_name(parm), "exec"),
                {"hou": hou, "kwargs": kwargs, "__builtins__": builtins},
            )
    except Exception as exc:
        # From the callback's own frame on (tb_next skips this function's exec
        # line), last few frames: what Houdini's dialog would have shown.
        frames = traceback.format_tb(exc.__traceback__.tb_next)[-4:]
        tail = "".join(frames).rstrip()
        raise CallbackError(
            f"Callback of {node.path()}/{parm.name()} raised {type(exc).__name__}: {exc}\n{tail}"
        ) from exc
    finally:
        with contextlib.suppress(Exception):
            hou.setPwd(previous)


def press(parm: hou.Parm, arguments: dict | None = None) -> str:
    """Do what a click on *parm* does; answer which route ran it.

    ``"python"`` -- its Python callback, executed here (CallbackError if it
    raises); ``"hscript"`` / ``"native"`` -- through pressButton(), which
    raises nothing for them and opens no error window.
    """
    script = callback_script(parm)
    if script and _is_python(parm):
        exec_python_callback(parm, script, _callback_kwargs(parm, arguments))
        return "python"
    if arguments:
        parm.pressButton(dict(arguments))
    else:
        parm.pressButton()
    return "hscript" if script else "native"
