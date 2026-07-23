rule = """
## Direct Source Verification Rule (Anti-Hallucination)
When checking anything, ALWAYS query the real source directly! Never rely on stale terminal logs, cached local states, or assumptions. You must actively SSH into Vultr, query the live database, or inspect the live remote files before diagnosing an issue or proposing a fix.
"""

with open(".agents/AGENTS.md", "a", encoding="utf-8") as f:
    f.write(rule)
print("Rule appended to AGENTS.md")
