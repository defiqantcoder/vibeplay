import ast

with open("src/vibeplay/web.py", "r") as f:
    web = f.read()

class RouteVisitor(ast.NodeVisitor):
    def __init__(self):
        self.routes = []

    def visit_FunctionDef(self, node):
        for dec in node.decorator_list:
            if hasattr(dec, "func") and hasattr(dec.func, "value") and hasattr(dec.func.value, "id"):
                if dec.func.value.id == "app":
                    arg = getattr(dec.args[0], "value", "") if dec.args else ""
                    self.routes.append((arg, node.name, dec.func.attr))
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

visitor = RouteVisitor()
tree = ast.parse(web)
visitor.visit(tree)

print(f"Found {len(visitor.routes)} route functions")
for path, name, method in visitor.routes:
    print(f"[{method}] {path} -> {name}")
