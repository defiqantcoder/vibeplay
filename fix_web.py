import re

with open("src/vibeplay/web.py", "r") as f:
    web = f.read()

# Let's count total @app. decorators
app_decs = re.findall(r'(\s*@app\.(?:post|get|put|delete)\(".*?)(?=\n\s*@app\.|\n\s*def|\Z)', web, re.DOTALL)
print(len(app_decs))
