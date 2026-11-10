import re

with open("src/vibeplay/web.py", "r") as f:
    web = f.read()

# Let's write a parser that parses the AST of web.py and extracts the function definitions that are decorated with @app.get/post/etc
import ast

tree = ast.parse(web)
create_app_node = None
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name == "create_app":
        create_app_node = node
        break

if not create_app_node:
    print("create_app not found")
    exit(1)

route_defs = []
for node in create_app_node.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id == "app"
                and dec.func.attr in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
                and dec.args
                and isinstance(dec.args[0], ast.Constant)
                and isinstance(dec.args[0].value, str)
            ):
                route_defs.append((node, dec.args[0].value))

print(f"Found {len(route_defs)} route functions inside create_app")
for node, path in route_defs:
    print(f"Path: {path}, Function: {node.name}")
