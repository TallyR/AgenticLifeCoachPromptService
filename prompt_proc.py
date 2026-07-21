# this is where prompts are processed

# Have a raw prompt text....

# Query conversation history, agent note, user note to gather context

import asyncio
from datetime import datetime, timezone
from enum import Enum

import anthropic

from message_api import TABLE, _get_client
from faro_system_prompt import FARO_SYSTEM_PROMPT

# Created once and reused (keeps its connection pool warm). Reads
# ANTHROPIC_API_KEY from the environment (loaded from .env by message_api).
_llm = anthropic.AsyncAnthropic()

# The md write paths aren't wired up yet. While True, get_md skips the DB
# entirely and just returns "EMPTY".
WRITE_PATH_MD_DISABLED = True


class MdType(Enum):
    """Which markdown table to read. Each carries its (table, field) pair."""
    USER = ("UserMdTable", "user_md")
    AGENT = ("AgentMdTable", "agent_md")

    def __init__(self, table: str, field: str):
        self.table = table
        self.field = field


async def get_md(phone_number: str, md_type: MdType) -> str:
    """Get the md text for a phone number from the USER or AGENT table. If none
    exists, create a row with the md field = "EMPTY" and return that text."""
    if WRITE_PATH_MD_DISABLED:
        return "EMPTY"

    client = await _get_client()
    response = await (
        client.table(md_type.table)
        .select("*")
        .eq("phone_number", phone_number)
        .execute()
    )
    if response.data:
        return response.data[0][md_type.field]

    inserted = await (
        client.table(md_type.table)
        .insert({"phone_number": phone_number, md_type.field: "EMPTY"})
        .execute()
    )
    return inserted.data[0][md_type.field]


async def set_md(phone_number: str, md_type: MdType, text: str) -> str:
    """Set the md text for a phone number in the USER or AGENT table, creating
    the row if it doesn't exist yet. Returns the saved text."""
    client = await _get_client()
    updated = await (
        client.table(md_type.table)
        .update({md_type.field: text})
        .eq("phone_number", phone_number)
        .execute()
    )
    if updated.data:
        return updated.data[0][md_type.field]

    inserted = await (
        client.table(md_type.table)
        .insert({"phone_number": phone_number, md_type.field: text})
        .execute()
    )
    return inserted.data[0][md_type.field]


async def get_conversation(phone_number: str) -> list[dict]:
    """Return every message to or from `phone_number`, oldest first (by sent_at)."""
    client = await _get_client()
    response = await (
        client.table(TABLE)
        .select("*")
        .or_(
            f"from_phone_number.eq.{phone_number},"
            f"to_phone_number.eq.{phone_number}"
        )
        .order("sent_at")
        .execute()
    )
    return response.data


def _render_history(rows: list[dict]) -> str:
    """Turn the conversation rows into timestamped plain-text lines for the prompt."""
    lines = []
    for row in rows:
        speaker = "Sarah" if row["from_phone_number"] == "AGENT" else "User"
        stamp = datetime.fromtimestamp(row["sent_at"], tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
        lines.append(f"[{stamp}] {speaker}: {row['message']}")
    return "\n".join(lines)


async def process_incoming_text(phone_number: str, newest_message: str) -> str:
    """Gather this user's notes and history, ask Sarah for a reply, print it."""
    # These three reads are independent, so run them at once.
    user_md, agent_md, history = await asyncio.gather(
        get_md(phone_number, MdType.USER),
        get_md(phone_number, MdType.AGENT),
        get_conversation(phone_number),
    )

    context = (
        f"<message_history>\n{_render_history(history)}\n</message_history>\n\n"
        f"<user_notes>\n{user_md}\n</user_notes>\n\n"
        f"<agent_notes>\n{agent_md}\n</agent_notes>\n\n"
        f"The user just texted you:\n{newest_message}"
    )

    response = await _llm.beta.messages.create(
        model="claude-fable-5",
        max_tokens=4096,
        system=FARO_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
        betas=["server-side-fallback-2026-06-01"],
        fallbacks=[{"model": "claude-opus-4-8"}],
    )

    reply = next((b.text for b in response.content if b.type == "text"), "")

    print(reply)
    return reply


# Have the model play a role.
    # my goal is to be agent that helps you accomplish your goals keeps you
        # from psycologically looping and checks in you to make sure you are on the right path. 
        # digital therapist that helps you stop negative thought patterns that you can text at anytime
        # like a digital therapist you can talk to and will check in you all the time!
# Have the model have a response.
# Have the model decide whether or not to edit the user.md file
# Have the model decide whether or not to edit the agent.md file
# (so much agent tools could be built here!)

# Need to reset the DB and double check this is working
if __name__ == "__main__":
    async def main():
        await process_incoming_text("+18323346991", "who are you?")
    asyncio.run(main())
