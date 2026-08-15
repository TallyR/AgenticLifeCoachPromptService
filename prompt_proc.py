# this is where prompts are processed

# Have a raw prompt text....

# Query conversation history, agent note, user note to gather context

import asyncio
import json
from datetime import datetime, timezone
from enum import Enum

import anthropic

from faro_delete_tool import (
    DeleteType,
    delete_reminder_or_event,
    get_delete_reminder_or_event_tool_definition,
)
from faro_events_api import (
    EVENT_TABLE,
    create_event,
    get_create_event_tool_definition,
    get_current_date_and_time_from_timezone,
    get_current_date_and_time_tool_definition,
)
from faro_reminders_api import (
    REMINDER_TABLE,
    create_reminder,
    get_create_reminder_tool_definition,
)
from faro_system_prompt import FARO_SYSTEM_PROMPT
from message_api import TABLE, _get_client

# Created once and reused (keeps its connection pool warm). Reads
# ANTHROPIC_API_KEY from the environment (loaded from .env by message_api).
_llm = anthropic.AsyncAnthropic()

# The md write paths aren't wired up yet. While True, get_md skips the DB
# entirely and just returns "EMPTY".
WRITE_PATH_MD_DISABLED = True

# Max model rounds per agent turn (call -> tools -> call -> ...). Lives here,
# not in api.py: api imports this module, so importing back would be circular.
AGENT_TURN_LIMIT = 10


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


async def should_send_contact_message(phone_number: str) -> bool:
    """True if this number hasn't been sent our contact card yet. Creates the
    UserMdTable row (user_md EMPTY, user_sent_contact_message false) for
    brand-new numbers."""
    client = await _get_client()
    response = await (
        client.table(MdType.USER.table)
        .select("user_sent_contact_message")
        .eq("phone_number", phone_number)
        .execute()
    )
    if response.data:
        return not response.data[0]["user_sent_contact_message"]

    await (
        client.table(MdType.USER.table)
        .insert(
            {
                "phone_number": phone_number,
                "user_md": "EMPTY",
                "user_sent_contact_message": False,
            }
        )
        .execute()
    )
    return True


async def mark_contact_message_sent(phone_number: str) -> None:
    """Flip user_sent_contact_message to true once the card has gone out."""
    client = await _get_client()
    await (
        client.table(MdType.USER.table)
        .update({"user_sent_contact_message": True})
        .eq("phone_number", phone_number)
        .execute()
    )


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


async def get_active_reminders_and_events(phone_number: str) -> str:
    """All reminders and events for this number, formatted for the prompt.

    Includes the row ids on purpose: they're what Faro passes to the delete
    tool when the user wants to remove or change an entry (change = delete +
    recreate, since there is no edit tool). Returns "NONE" when empty.
    """
    client = await _get_client()
    reminders, events = await asyncio.gather(
        client.table(REMINDER_TABLE)
        .select("*")
        .eq("user_number", phone_number)
        .execute(),
        client.table(EVENT_TABLE)
        .select("*")
        .eq("user_number", phone_number)
        .execute(),
    )

    lines = []
    for r in reminders.data:
        occurrences = (
            "repeats forever"
            if r["number_of_occurrences"] == -1
            else f"{r['number_of_occurrences']} occurrences left"
        )
        lines.append(
            f"REMINDER id={r['id']}: every {', '.join(r['days_of_week'])} at "
            f"{r['hour_to_be_triggered']}:{r['minute_to_be_triggered']:02d}:"
            f"{r['second_to_be_triggered']:02d} {r['am_or_pm']} "
            f"({r['timezone']}), {occurrences} — \"{r['note']}\""
        )
    for e in events.data:
        lines.append(
            f"EVENT id={e['id']}: {e['year']}-{e['month']:02d}-{e['day']:02d} "
            f"at {e['hour']}:{e['minute']:02d}:{e['second']:02d} "
            f"{e['am_or_pm']} ({e['timezone']}) — \"{e['note']}\""
        )

    return "\n".join(lines) if lines else "NONE"


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


async def _execute_tool(name: str, tool_input: dict, phone_number: str) -> str:
    """Dispatch one tool call by name; returns the result as JSON text.
    phone_number is injected here — the model never controls it."""
    if name == "get_current_date_and_time_from_timezone":
        return json.dumps(get_current_date_and_time_from_timezone(**tool_input))
    if name == "create_event":
        row = await create_event(**tool_input, user_number=phone_number)
        return json.dumps(row)
    if name == "create_reminder":
        row = await create_reminder(**tool_input, user_number=phone_number)
        return json.dumps(row)
    if name == "delete_reminder_or_event":
        deleted = await delete_reminder_or_event(
            tool_input["row_id"], DeleteType[tool_input["delete_type"]]
        )
        return json.dumps(
            {"deleted": deleted}
            if deleted
            else {"deleted": False, "reason": "no row with that id"}
        )
    raise ValueError(f"unknown tool: {name}")


async def process_incoming_text(phone_number: str, newest_message: str) -> tuple[str, bool]:
    """Gather this user's context, then run the agent loop: Faro can call its
    tools (current time, events, reminders, delete), each result is fed back
    into the in-turn conversation, and the loop ends when it answers in plain
    text. Tool calls are printed but never saved to Supabase — only the
    incoming text and the final reply reach MessageTable (saved by api.py).
    Returns (reply, send_contact_card)."""
    # ############################ BIG ASS WARNING ############################
    # should_send_contact_message is only safe inside this gather while
    # WRITE_PATH_MD_DISABLED is True (get_md never touches the DB). The moment
    # you re-enable the md write path, get_md(USER) and
    # should_send_contact_message will RACE to insert the UserMdTable row for a
    # brand-new number and can double-insert. At that point, pull
    # should_send_contact_message OUT of this gather and await it BEFORE.
    # #########################################################################
    user_md, agent_md, history, send_contact_card, active_items = await asyncio.gather(
        get_md(phone_number, MdType.USER),
        get_md(phone_number, MdType.AGENT),
        get_conversation(phone_number),
        should_send_contact_message(phone_number),
        get_active_reminders_and_events(phone_number),
    )

    context = (
        f"<message_history>\n{_render_history(history)}\n</message_history>\n\n"
        f"<user_notes>\n{user_md}\n</user_notes>\n\n"
        f"<agent_notes>\n{agent_md}\n</agent_notes>\n\n"
        f"<active_reminders_and_events>\n{active_items}\n</active_reminders_and_events>\n\n"
        f"The user just texted you:\n{newest_message}"
    )

    messages = [{"role": "user", "content": context}]
    tools = [
        get_current_date_and_time_tool_definition(),
        get_create_event_tool_definition(),
        get_create_reminder_tool_definition(),
        get_delete_reminder_or_event_tool_definition(),
    ]

    for _ in range(AGENT_TURN_LIMIT):
        response = await _llm.beta.messages.create(
            model="claude-fable-5",
            max_tokens=4096,
            system=FARO_SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
            betas=["server-side-fallback-2026-06-01"],
            fallbacks=[{"model": "claude-opus-4-8"}],
        )

        # Append the assistant turn verbatim — this keeps the thinking and
        # tool_use blocks intact, which the API requires on replay.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            reply = next((b.text for b in response.content if b.type == "text"), "")
            print(reply)
            return reply, send_contact_card

        # Execute every tool call in the turn, then send all results back in
        # a single user message (matched by tool_use_id). These live only in
        # this in-turn conversation: printed, never saved to Supabase.
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"[tool call] {block.name}({json.dumps(block.input)})")
            try:
                content = await _execute_tool(block.name, block.input, phone_number)
                print(f"[tool result] {content}")
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content,
                    }
                )
            except Exception as e:
                print(f"[tool error] {e}")
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(e),
                        "is_error": True,
                    }
                )
        messages.append({"role": "user", "content": tool_results})

    # Cap hit: never send the user an empty text. Log loudly for Render logs
    # and hand back something human.
    print(f"AGENT LOOP HIT ITS {AGENT_TURN_LIMIT}-ROUND CAP WITHOUT FINISHING")
    reply = "ugh, something glitched on my end. say that one more time?"
    return reply, send_contact_card


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
    # Local import: api imports this module, so a top-level `from api` is circular.
    from api import _send_with_retries
    from message_api import FARO_VCF_URL

    async def main():
        # await process_incoming_text("+18323346991", "who are you?")
        number = "+18323346991"
        if await should_send_contact_message(number):
            # contact card = greeting + Faro's .vcf attached (mirrors api.py step 4)
            await _send_with_retries(
                number,
                "oh, also, here is my contact card you should save in order to make sure you can find me again :)",
                attachments=[FARO_VCF_URL],
            )
            await mark_contact_message_sent(number)
            print(f"contact card sent to {number}, flag flipped to true")
        else:
            print(f"{number} already got the contact card, skipping")
    asyncio.run(main())
