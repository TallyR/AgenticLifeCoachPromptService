from datetime import datetime
from zoneinfo import ZoneInfo

from message_api import _get_client

EVENT_TABLE = "EventToolTable"


async def create_event(
    timezone: str,
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
    am_or_pm: str,
    note: str,
    user_number: str,
) -> dict:
    """Write one event row to the EventToolTable and return it.

    `id` and `created_at` are filled in by the DB, so they are not passed here.
    Uses the 12-hour clock (hour 1-12 plus am_or_pm), same as reminders.

    Args:
        timezone: IANA timezone name, e.g. "America/New_York".
        year: Four-digit year, e.g. 2026.
        month: Month (1-12).
        day: Day of the month (1-31).
        hour: Hour on a 12-hour clock (1-12), paired with am_or_pm.
        minute: Minute (0-59).
        second: Second (0-59).
        am_or_pm: "AM" or "PM".
        note: The event text to send to the user when it fires.
        user_number: The recipient's phone number.
    """
    client = await _get_client()
    response = await (
        client.table(EVENT_TABLE)
        .insert(
            {
                "timezone": timezone,
                "year": year,
                "month": month,
                "day": day,
                "hour": hour,
                "minute": minute,
                "second": second,
                "am_or_pm": am_or_pm,
                "note": note,
                "user_number": user_number,
            }
        )
        .execute()
    )
    return response.data[0]


def get_current_date_and_time_from_timezone(timezone: str) -> dict:
    """Current date and time in the given IANA timezone (e.g. "America/New_York").

    Uses the 12-hour clock (hour 1-12 plus am_or_pm) to match how reminders
    and events are stored, and includes the spelled-out day of the week.
    Raises ZoneInfoNotFoundError for an invalid timezone name.
    """
    now = datetime.now(ZoneInfo(timezone))
    days = [
        "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday",
    ]
    return {
        "year": now.year,
        "month": now.month,
        "day": now.day,
        # Manual 12-hour conversion instead of strftime("%I"/"%p"): those are
        # locale-dependent, and this must always be 1-12 + "AM"/"PM" exactly.
        "hour": now.hour % 12 or 12,
        "minute": now.minute,
        "second": now.second,
        "am_or_pm": "AM" if now.hour < 12 else "PM",
        "day_of_week": days[now.weekday()],
    }


def get_current_date_and_time_tool_definition() -> dict:
    """Anthropic tool definition for get_current_date_and_time_from_timezone."""
    return {
        "name": "get_current_date_and_time_from_timezone",
        "description": (
            "Get the current date and time where the user is, on the 12-hour "
            "clock (hour 1-12 plus am_or_pm) — the same format reminders and "
            "events use — plus the day of the week. Call this FIRST whenever "
            "a request depends on knowing the current time: relative times "
            "like 'in 5 minutes' or 'in an hour', resolving 'tomorrow' or "
            "'next friday' to a concrete date, or checking whether a time has "
            "already passed today. You do not know the current time on your "
            "own — never guess it; call this and do the arithmetic from the "
            "result."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": (
                        "The user's timezone as an IANA name, e.g. "
                        "'America/New_York'. Infer it from what you know "
                        "about the user; if you can't, ask them for their "
                        "city and derive it."
                    ),
                },
            },
            "required": ["timezone"],
        },
    }


def get_create_event_tool_definition() -> dict:
    """Anthropic tool definition for create_event.

    user_number is deliberately NOT in the schema — it's injected
    programmatically from the webhook, never chosen by the model."""
    return {
        "name": "create_event",
        "description": (
            "Create a one-off event: a single alarm that gets texted to the "
            "user exactly once, at a specific date and time, and never again. "
            "Use this for single moments — 'wake me up at 7am tomorrow', "
            "'ping me about my dentist appointment on the 15th at 2pm'. For "
            "anything recurring or ongoing ('every tuesday', 'each morning'), "
            "use create_reminder instead; events are strictly one-time. "
            "Resolve relative dates like 'tomorrow' or 'next friday' into the "
            "concrete year, month, and day in the user's timezone before "
            "calling. The note is the text the user receives when the event "
            "fires, so write it like a message from you, not a system alert. "
            "If you can't determine the user's timezone from context, don't "
            "guess — ask what city they're in and derive it from that."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": (
                        "The user's timezone as an IANA name, e.g. "
                        "'America/New_York' or 'America/Chicago'. Infer it "
                        "from what you know about the user; if you can't, "
                        "ask them for their city and derive it."
                    ),
                },
                "year": {
                    "type": "integer",
                    "minimum": 2025,
                    "description": "Four-digit year the event fires, e.g. 2026.",
                },
                "month": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 12,
                    "description": "Month (1-12).",
                },
                "day": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 31,
                    "description": "Day of the month (1-31).",
                },
                "hour": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 12,
                    "description": "Hour on a 12-hour clock (1-12), paired with am_or_pm.",
                },
                "minute": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 59,
                    "description": "Minute (0-59). A bare hour like '8pm' means 0.",
                },
                "second": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 59,
                    "description": "Second (0-59). Almost always 0.",
                },
                "am_or_pm": {
                    "type": "string",
                    "enum": ["AM", "PM"],
                    "description": "Exactly 'AM' or 'PM'. Required.",
                },
                "note": {
                    "type": "string",
                    "description": (
                        "The text the user receives when the event fires. "
                        "Make it relevant to what they asked for and fun — "
                        "it's their alarm message, written in your voice."
                    ),
                },
            },
            "required": [
                "timezone",
                "year",
                "month",
                "day",
                "hour",
                "minute",
                "second",
                "am_or_pm",
                "note",
            ],
        },
    }


#### FOR DEBUGGING PURPOSES: FULL HARNESS HERE ####
if __name__ == "__main__":
    import asyncio
    import json

    from faro_delete_tool import (
        DeleteType,
        delete_entry,
        get_delete_entry_tool_definition,
    )
    from faro_nag_tool import create_nag, get_nag_tool_definition
    from faro_reminders_api import (
        create_reminder,
        get_create_reminder_tool_definition,
    )
    from faro_system_prompt import FARO_SYSTEM_PROMPT
    from prompt_proc import (
        AGENT_TURN_LIMIT,
        OUTPUT_MAX_TOKENS,
        MdType,
        _llm,
        _render_history,
        get_active_commitments,
        get_conversation,
        get_md,
    )

    TEST_NUMBER = "+18323346991"

    async def _execute_tool(name: str, tool_input: dict) -> str:
        """Dispatch one tool call by name; returns the result as JSON text."""
        if name == "get_current_date_and_time_from_timezone":
            return json.dumps(get_current_date_and_time_from_timezone(**tool_input))
        if name == "create_event":
            row = await create_event(**tool_input, user_number=TEST_NUMBER)
            return json.dumps(row)
        if name == "create_reminder":
            row = await create_reminder(**tool_input, user_number=TEST_NUMBER)
            return json.dumps(row)
        if name == "create_nag":
            row = await create_nag(**tool_input, user_number=TEST_NUMBER)
            return json.dumps(row)
        if name == "delete_entry":
            deleted = await delete_entry(
                tool_input["row_id"], DeleteType[tool_input["delete_type"]]
            )
            return json.dumps(
                {"deleted": deleted}
                if deleted
                else {"deleted": False, "reason": "no row with that id"}
            )
        raise ValueError(f"unknown tool: {name}")

    async def _run_agent_turn(messages: list, tools: list) -> None:
        """One Faro turn: call the model, execute any tool calls, feed the
        results back, repeat until it answers in plain text."""
        for _ in range(AGENT_TURN_LIMIT):
            response = await _llm.beta.messages.create(
                model="claude-fable-5",
                max_tokens=OUTPUT_MAX_TOKENS,
                system=FARO_SYSTEM_PROMPT,
                messages=messages,
                tools=tools,
                betas=["server-side-fallback-2026-06-01"],
                fallbacks=[{"model": "claude-opus-4-8"}],
            )

            # Append the assistant turn verbatim — this keeps the thinking
            # and tool_use blocks intact, which the API requires on replay.
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                reply = next(
                    (b.text for b in response.content if b.type == "text"), ""
                )
                print(f"\nFARO: {reply}")
                return

            # Execute every tool call in the turn, then send all results
            # back in a single user message (matched by tool_use_id).
            # Errors go back with is_error so Faro can see and correct.
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                print(f"\n[tool call] {block.name}({json.dumps(block.input)})")
                try:
                    content = await _execute_tool(block.name, block.input)
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

        print(f"agent loop hit its {AGENT_TURN_LIMIT}-round cap without finishing")

    async def _chat() -> None:
        """Interactive verification harness: text Faro from the terminal with
        the FULL toolbox — current time, one-off events, recurring reminders,
        and delete — plus the live schedule context block, same as production
        will have. Nothing is texted or saved to MessageTable; tool calls DO
        write and delete real reminder/event rows.

        One asyncio.run for the whole session on purpose: the shared clients
        bind to the first event loop, so per-message loops would break them.
        """
        user_md, agent_md, history, active_items = await asyncio.gather(
            get_md(TEST_NUMBER, MdType.USER),
            get_md(TEST_NUMBER, MdType.AGENT),
            get_conversation(TEST_NUMBER),
            get_active_commitments(TEST_NUMBER),
        )
        preamble = (
            f"<message_history>\n{_render_history(history)}\n</message_history>\n\n"
            f"<user_notes>\n{user_md}\n</user_notes>\n\n"
            f"<agent_notes>\n{agent_md}\n</agent_notes>\n\n"
            f"<active_commitments>\n{active_items}\n</active_commitments>\n\n"
            f"The user just texted you:\n"
        )
        messages: list = []
        tools = [
            get_current_date_and_time_tool_definition(),
            get_create_event_tool_definition(),
            get_create_reminder_tool_definition(),
            get_nag_tool_definition(),
            get_delete_entry_tool_definition(),
        ]

        print(
            "texting Faro (time + event + reminder + delete tools, live schedule "
            "loaded) — empty message or Ctrl+C to quit"
        )
        while True:
            try:
                incoming = input("\nYOU: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not incoming:
                break

            if not messages:
                # First turn carries the DB context; later turns are plain.
                messages.append({"role": "user", "content": preamble + incoming})
            else:
                messages.append({"role": "user", "content": incoming})

            await _run_agent_turn(messages, tools)

    asyncio.run(_chat())
