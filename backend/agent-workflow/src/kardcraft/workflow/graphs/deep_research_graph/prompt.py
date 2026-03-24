"""Prompts for deep research graph."""


def get_main_system_prompt(language: str | None = None) -> str:
    lang = (language or "auto").strip()
    return (
        "You are a deep research coordinator. "
        "Delegate focused research to sub-agent(s), gather evidence, and return a concise synthesis. "
        f"Preferred language: {lang}."
    )


def get_researcher_system_prompt(language: str | None = None) -> str:
    lang = (language or "auto").strip()
    return (
        "You are a researcher. Use quick_research and think_tool to iteratively gather evidence. "
        "Stop when information is sufficient. "
        f"Output language: {lang}."
    )

