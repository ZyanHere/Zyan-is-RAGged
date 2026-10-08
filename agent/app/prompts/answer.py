"""The grounded-answer prompt.

In its own module because a prompt is *behaviour*, not plumbing. When stage 18.1
makes prompts versioned artifacts with an eval run per version, this is the file
it formalises — and `PROMPT_VERSION` is the seed of that, so bump it whenever
the text below changes.

The prompt does two jobs: confine the model to the supplied excerpts, and make
it mark which excerpt each claim came from so citations can be resolved to
pages. Both are enforced weakly — by instruction. Stage 17.2 adds a programmatic
check that a cited span actually supports its claim, and 17.3 adds a real
abstention gate. Until then, an instruction is what we have, and knowing it is
weak is the point.
"""

PROMPT_VERSION = "answer-v1"

SYSTEM_PROMPT = """\
You answer questions using only the numbered excerpts provided by the user.

Rules:
- Use only the excerpts. Do not use anything you know from outside them.
- After each claim, cite the excerpt it came from using its number in square
  brackets, like [1]. Cite several as [1][3] when a claim draws on more than one.
- If the excerpts do not contain the answer, say exactly that and stop. Do not
  guess, and do not fill the gap with general knowledge.
- If the excerpts disagree with each other, say so and cite both. Do not pick
  one silently.
- Answer in plain prose. Be brief. Do not restate the question.\
"""

USER_TEMPLATE = """\
Excerpts:

{context}

Question: {question}\
"""

EXCERPT_TEMPLATE = """\
[{marker}] {filename}, page {page}
{text}\
"""
