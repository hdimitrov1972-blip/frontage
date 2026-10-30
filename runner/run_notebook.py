"""Run one Colab notebook on the server, top to bottom, like "Run all" in Colab.

    python runner/run_notebook.py NOTEBOOK.ipynb [--set NAME=VALUE ...]

- Code cells run in order in one shared namespace, exactly as written.
- Shell lines ("!pip install ...") are skipped: packages are installed beforehand.
- --set replaces one single-line setting, e.g. --set 'TOWN="Drogheda"' or
  --set 'TEST_SEND_TO=[]'. The notebook itself is never changed on Drive.
- Exit code 0 = every cell finished, 1 = a cell failed (traceback printed).
"""
import ast
import json
import os
import re
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import colab_stub  # noqa: E402


def load_cells(path):
    with open(path, encoding="utf-8") as f:
        nb = json.load(f)
    cells = []
    for c in nb.get("cells", []):
        if c.get("cell_type") == "code":
            src = c.get("source", "")
            cells.append("".join(src) if isinstance(src, list) else src)
    return cells


def strip_shell_lines(src):
    out = []
    for line in src.splitlines():
        body = line.lstrip()
        if body.startswith(("!", "%")):
            out.append(line[: len(line) - len(body)] + "pass  # shell line skipped on the server")
        else:
            out.append(line)
    return "\n".join(out)


def apply_settings(cells, settings):
    """Replace `NAME = ...` (a complete one-line, top-level assignment) in the first cell that has it."""
    for name, value in settings.items():
        ast.parse(f"{name} = {value}")                      # the new value must be valid Python
        pat = re.compile(rf"^{re.escape(name)}\s*=.*$", re.M)
        for i, src in enumerate(cells):
            m = pat.search(src)
            if not m:
                continue
            line = m.group(0)
            try:
                ast.parse(line)
            except SyntaxError:
                raise SystemExit(f"setting {name} spans several lines in the notebook; cannot replace it safely")
            comment = ""
            if "#" in line:                                  # keep a trailing comment, if any
                try:
                    ast.parse(line[: line.index("#")])
                    comment = "  " + line[line.index("#"):]
                except SyntaxError:
                    pass
            cells[i] = src[: m.start()] + f"{name} = {value}{comment}" + src[m.end():]
            break
        else:
            raise SystemExit(f"setting {name} not found in the notebook")
    return cells


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    path, settings = argv[0], {}
    rest = argv[1:]
    while rest:
        if rest[0] != "--set" or len(rest) < 2 or "=" not in rest[1]:
            raise SystemExit(__doc__)
        name, value = rest[1].split("=", 1)
        settings[name.strip()] = value.strip()
        rest = rest[2:]

    colab_stub.install()
    cells = apply_settings([strip_shell_lines(c) for c in load_cells(path)], settings)
    namespace = {"__name__": "__main__", "display": print}
    for n, src in enumerate(cells, 1):
        print(f"\n######## cell {n} of {len(cells)} ########", flush=True)
        try:
            exec(compile(src, f"{os.path.basename(path)} cell {n}", "exec"), namespace)
        except SystemExit as e:
            if e.code not in (None, 0):
                print(f"cell {n} stopped the notebook: {e}", flush=True)
                return 1
        except BaseException:
            traceback.print_exc()
            sys.stdout.flush()
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
