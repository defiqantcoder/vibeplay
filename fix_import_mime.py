with open("src/vibeplay/desktop/mime.py", "r") as f:
    lines = f.readlines()

new_lines = []
security_import = []
in_security_import = False
for line in lines:
    if line.startswith("from vibeplay.desktop.security import"):
        in_security_import = True
        security_import.append(line)
    elif in_security_import:
        security_import.append(line)
        if line.strip() == ")":
            in_security_import = False
    else:
        new_lines.append(line)

# find where to insert security_import
for i, line in enumerate(new_lines):
    if line.startswith("logger = logging.getLogger"):
        new_lines = new_lines[:i] + security_import + new_lines[i:]
        break

with open("src/vibeplay/desktop/mime.py", "w") as f:
    f.writelines(new_lines)
