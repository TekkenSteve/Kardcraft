# dspy_langfuse

## Stable runtime API
Use only these imports in production code:

- `kardcraft.dspy_langfuse.PromptResolver`
- `kardcraft.dspy_langfuse.ResolvedPrompt`

## Experimental API
Legacy/experimental utilities are moved under:

- `kardcraft.dspy_langfuse.experimental.*`

Compatibility shim modules remain at old paths for transition, but new code should not use them.
