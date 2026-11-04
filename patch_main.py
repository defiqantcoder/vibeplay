import re

with open("src/vibeplay/desktop/__main__.py", "r") as f:
    content = f.read()

# Add asyncio import
content = content.replace("import argparse", "import argparse\nimport asyncio")

# Wrap forward_uris_to_running_instance call in asyncio.run
old_call = "if forward_uris_to_running_instance(args.uris, host=args.host, port=args.port):"
new_call = "if asyncio.run(forward_uris_to_running_instance(args.uris, host=args.host, port=args.port)):"

content = content.replace(old_call, new_call)

with open("src/vibeplay/desktop/__main__.py", "w") as f:
    f.write(content)
