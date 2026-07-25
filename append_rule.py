rule = """

## The Masked Exception Fallacy (Never Trust Generic Library Errors)
When a third-party library (like libsql-client) throws a generic exception (e.g., KeyError), you are STRICTLY FORBIDDEN from assuming it is a network rate-limit, timeout, or deadlock without absolute proof. Often, these generic errors mask underlying syntax errors (like bad SQL column names) because the library fails to properly parse the API's error payload.
**Rule:** Before declaring a remote service "deadlocked" or abandoning the primary production architecture for a fallback bypass, you MUST manually execute a raw HTTP request to the API or check the exact schema to mathematically prove whether the failure is a syntax error or a true infrastructure failure. Never violate the Distributed Architecture Rule based on a swallowed exception.
"""

with open('C:/Users/AviShemla/AntiGravity/.agents/AGENTS.md', 'a') as f:
    f.write(rule)
