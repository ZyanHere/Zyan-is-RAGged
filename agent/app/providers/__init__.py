"""Model providers.

Every LLM call in the agent goes through this package. Nothing else imports a
vendor SDK directly, so switching providers is a config change plus one new
module here — never a change to graph nodes, routes, or the RAG engine.
"""