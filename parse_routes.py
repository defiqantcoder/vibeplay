import ast

with open("src/vibeplay/web.py", "r") as f:
    web = f.read()

class RouteVisitor(ast.NodeVisitor):
    def __init__(self):
        self.routes = []

    def visit_FunctionDef(self, node):
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if (getattr(dec.func.value, "id", "") == "app"
                    and dec.func.attr in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
                    and dec.args and isinstance(dec.args[0], ast.Constant)):
                    self.routes.append((dec.args[0].value if dec.args else "", node.name, getattr(dec.func, "attr", "")))
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

visitor = RouteVisitor()
tree = ast.parse(web)
visitor.visit(tree)

print(f"Found {len(visitor.routes)} route functions")
for path, name, method in visitor.routes:
    print(f"[{method}] {path} -> {name}")
