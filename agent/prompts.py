"""Prompt templates for TokenSlim autonomous coding agent.
Emphasizes minimal patches, exact context matching, and token efficiency.
"""

SYSTEM_CODING_PROMPT = """You are TokenSlim, an autonomous, token-efficient software engineering agent.
Your objective is to complete the task by generating the minimal possible code edit.

Guidelines:
1. NEVER regenerate entire files. Produce only focused search-and-replace blocks.
2. The SEARCH block must match EXACT character-for-character code in the target file, including indentation.
3. Keep SEARCH blocks small (3-15 lines) with just enough context to be unique.
4. If a test failure is provided, address the root cause directly.

Output Format:
FILE: path/to/file.py
<<<<<<< SEARCH
exact original code
=======
replacement code
>>>>>>> REPLACE
"""

def build_repair_prompt(
    task_directive: str,
    context_code: str,
    failing_test_summary: str,
    traceback_excerpt: str,
    iteration: int,
    patch_error: str = ""
) -> str:
    """Build concise prompt for code patch or repair."""
    parts = [
        f"### TASK DIRECTIVE\n{task_directive}\n",
        f"### RELEVANT CODE CONTEXT\n{context_code}\n"
    ]

    if failing_test_summary:
        parts.append(f"### TEST STATUS (Attempt {iteration})\n{failing_test_summary}\n")

    if traceback_excerpt:
        parts.append(f"### TRACEBACK EXCERPT\n{traceback_excerpt}\n")

    if patch_error:
        parts.append(f"### PREVIOUS PATCH APPLICATION ERROR\n{patch_error}\nEnsure the SEARCH block matches the file exactly.\n")

    parts.append("Generate the exact minimal search-and-replace block to resolve the issue.")
    return "\n".join(parts)
