"""Extract overlapping inline handlers into the existing player/settings routers.

Factories retain create_app's per-application state. Existing standalone routers
remain available for callers that import them directly.
"""

import ast
from pathlib import Path

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def route_decorators(node, owner):
    for dec in node.decorator_list:
        if (
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and isinstance(dec.func.value, ast.Name)
            and dec.func.value.id == owner
            and dec.func.attr in HTTP_METHODS
            and dec.args
            and isinstance(dec.args[0], ast.Constant)
            and isinstance(dec.args[0].value, str)
        ):
            yield dec


def extract_routes(root=Path("src/vibeplay")):
    web_path = root / "web.py"
    source = web_path.read_text()
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    create_app = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_app")
    removals = []
    outputs = {}
    mounts = []
    for name, prefix in (("player", "/api/player"), ("settings", "")):
        router_path = root / "routers" / f"{name}.py"
        router_source = router_path.read_text()
        router_tree = ast.parse(router_source)
        expected = {
            (dec.func.attr, prefix + dec.args[0].value)
            for node in router_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for dec in route_decorators(node, "router")
        }
        handlers = []
        for node in create_app.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = list(route_decorators(node, "app"))
            if not any((d.func.attr, d.args[0].value) in expected for d in decorators):
                continue
            if any((d.func.attr, d.args[0].value) not in expected for d in decorators):
                raise ValueError(f"Mixed router ownership for {node.name}")
            start = min(d.lineno for d in node.decorator_list) - 1
            handler = lines[start:node.end_lineno].copy()
            for dec in decorators:
                index = dec.lineno - 1 - start
                handler[index] = handler[index].replace("@app.", "@router.", 1)
                if prefix:
                    # Only the path literal changes; all decorator options stay intact.
                    literal = ast.get_source_segment(source, dec.args[0])
                    handler[index] = handler[index].replace(literal, repr(dec.args[0].value[len(prefix):]), 1)
            handlers.append("".join(handler))
            removals.append((start, node.end_lineno))
        if not handlers:
            continue
        if any(isinstance(n, ast.FunctionDef) and n.name == "build_router" for n in router_tree.body):
            raise ValueError(f"{name} already has a router factory")
        imports = ""
        if name == "player":
            imports = "    from vibeplay.player import adjust_volume_step, set_volume_level\n\n"
        else:
            imports = "    from vibeplay.player import set_output_profile\n\n"
        factory = (
            "\n\ndef build_router(cfg, resolved_db_path, templates, settings_file_path, _sync_runtime_cfg):\n"
            '    """Bind the original web handlers to this application\'s state."""\n'
            + imports
            + f"    router = APIRouter(prefix={prefix!r}, tags=[{name!r}])\n\n"
            + "\n\n".join(handlers)
            + "\n    return router\n"
        )
        outputs[router_path] = router_source + factory
        mounts.append(
            f"    from vibeplay.routers.{name} import build_router as build_{name}_router\n\n"
            f"    app.include_router(build_{name}_router(cfg, resolved_db_path, templates, settings_file_path, _sync_runtime_cfg))\n\n"
        )
    if not removals:
        return
    for start, end in sorted(removals, reverse=True):
        del lines[start:end]
    updated = "".join(lines)
    # Mount in the same create_app flow as the established library/root routers.
    anchor = "    app.include_router(library_router)"
    if anchor not in updated:
        raise ValueError("Existing router setup not found")
    outputs[web_path] = updated.replace(anchor, "".join(mounts) + anchor, 1)
    for path, content in outputs.items():
        ast.parse(content)
    for path, content in outputs.items():
        path.write_text(content)


if __name__ == "__main__":
    extract_routes()
