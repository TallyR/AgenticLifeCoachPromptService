# Reconciliation script: replays every user's message history through a
# data-migration agent that backfills the state tables (settings, location,
# nags, reminders, events) using the same tools production uses.
#
# NOT part of the serving path. Sends NOTHING to any user — the only side
# effects are tool writes to Supabase. Run it as many times as you like:
# the prompt is written to converge, so a second pass over unchanged data
# should report NO CHANGES for every user.
#
# Context: message history is currently the only complete memory. Once state
# reliably lives in the tables (this script backfills old users; the live
# tools capture it for new traffic), history can be capped to a rolling
# window without losing durable state.
#
# Usage: python transition.py                (all users)
#        python transition.py +18323346991   (one user)
# NOTE: costs one Fable agent run per user, and mutates real tables.

import asyncio
import json

from faro_delete_tool import get_delete_entry_tool_definition
from faro_nag_tool import get_nag_tool_definition
from faro_user_location_tool import (
    get_set_user_timezone_tool_definition,
    get_user_timezone,
)
from faro_user_settings_tool import (
    get_user_settings,
    get_user_settings_tool_definition,
)
from daily_summaries_api import ENABLED_DAILY_SUMMARIES_TABLE
from message_api import TABLE, _get_client
from prompt_proc import (
    MdType,
    OUTPUT_MAX_TOKENS,
    _execute_tool,
    _llm,
    _render_history,
    get_active_commitments,
    get_conversation,
)

RECONCILE_TURN_LIMIT = 10

# Tool names that mutate state — these are the "changes" we report per user.
MUTATING_TOOLS = {
    "create_user_setting",
    "set_user_timezone",
    "create_nag",
    "delete_entry",
}

TRANSITION_PROMPT = """\
You are a data reconciliation agent for Faro, a text-message accountability \
companion. You are NOT talking to a user and no message you write is ever \
sent to one. You receive one user's full message history plus their current \
recorded state, and your job is to make the recorded state match what the \
history establishes, using your tools. This is a backfill: history is the \
source of truth, the tables are catching up.

You reconcile exactly three kinds of state — the newly introduced tools:
- user settings (create_user_setting): their name, country, grammar or \
capitalization preference, what they use faro for. One note per fact.
- location (set_user_timezone): their city plus the IANA timezone inferred \
from it, formatted like "new york — America/New_York". One record per user; \
setting it again overwrites.
- standing nags (create_nag): "keep after me until it's done" items with no \
schedule, still open per the history. Closed means closed: "nag me about \
the passport" followed anywhere later by "renewed it" (or "stop nagging me \
about that") is NOT a nag — it already ended inside the history. Only \
record a nag if nothing later in the history closes it.

OUT OF SCOPE: recurring reminders and one time events. Those are captured \
by the live tools already. Never create one, and never delete or modify a \
REMINDER or EVENT entry you see in the current state — they are shown only \
so you know what exists. You also receive <other_recorded_state> (the \
daily summary flag and the md notes tables): read only, no tool in your \
kit touches them, they're included so you see the complete picture.

Hard rules:
- IDEMPOTENT ABOVE ALL. The current recorded state is provided below. If a \
fact is already recorded, do NOT record it again. If nothing is missing, \
make zero tool calls. Repeated runs of this script over the same data must \
produce no new changes.
- Newest statement wins, within your three kinds. If the history shows a \
change of mind (moved cities, said a nagged task is done, changed a \
preference), the final state reflects the newest statement — which may mean \
recording nothing, or deleting a stale SETTING or NAG entry with \
delete_entry.
- Deduplicate, within your three kinds. If the same fact appears twice in \
the recorded state (e.g. two identical setting notes from an earlier run), \
delete the extras with delete_entry, keeping one.
- Record only what the user clearly established. No inferences from vibes, \
no passing remarks promoted to durable state. When unsure, leave it out.
- A nag's note is text the user will eventually see in their daily rundown: \
keep the wording the history shows they wanted, or a short faithful \
phrasing. Lowercase, warm, brief.

Your final reply is a change log for the operator, not a message to the \
user: one line per change you made ("recorded setting: name: hassan", \
"set location: new york — America/New_York", "deleted duplicate setting \
id=7"). If you made no tool calls, reply exactly: NO CHANGES\
"""


async def get_all_user_numbers() -> list[str]:
    """Every distinct user number that appears in the message history."""
    client = await _get_client()
    rows = await (
        client.table(TABLE).select("from_phone_number, to_phone_number").execute()
    )
    numbers = set()
    for row in rows.data:
        for key in ("from_phone_number", "to_phone_number"):
            value = row[key]
            if value and value != "AGENT":
                numbers.add(value)
    return sorted(numbers)


async def get_auxiliary_state(phone_number: str) -> str:
    """Read-only snapshot of the remaining per-user tables, so the agent
    sees the complete picture even though no tool in its kit touches these.
    NB the column names differ per table (phone_number here)."""
    client = await _get_client()
    daily, user_md, agent_md = await asyncio.gather(
        client.table(ENABLED_DAILY_SUMMARIES_TABLE)
        .select("*")
        .eq("phone_number", phone_number)
        .execute(),
        client.table(MdType.USER.table)
        .select("*")
        .eq("phone_number", phone_number)
        .execute(),
        client.table(MdType.AGENT.table)
        .select("*")
        .eq("phone_number", phone_number)
        .execute(),
    )
    return json.dumps(
        {
            "daily_summaries": daily.data[0] if daily.data else None,
            "user_md": user_md.data[0] if user_md.data else None,
            "agent_md": agent_md.data[0] if agent_md.data else None,
        }
    )


async def reconcile_user(phone_number: str) -> list[str]:
    """Run the reconciliation agent for one user. Returns the list of
    mutating tool calls it made (empty = already converged)."""
    history, settings, commitments, location, auxiliary = await asyncio.gather(
        get_conversation(phone_number),
        get_user_settings(phone_number),
        get_active_commitments(phone_number),
        get_user_timezone(phone_number),
        get_auxiliary_state(phone_number),
    )

    context = (
        f"user: {phone_number}\n\n"
        f"<message_history>\n{_render_history(history)}\n</message_history>\n\n"
        f"<current_user_settings>\n{settings}\n</current_user_settings>\n\n"
        f"<current_location_record>\n{json.dumps(location)}\n</current_location_record>\n\n"
        f"<current_active_commitments>\n{commitments}\n</current_active_commitments>\n\n"
        f"<other_recorded_state>\n{auxiliary}\n</other_recorded_state>\n\n"
        "Reconcile this user's recorded state with their history now."
    )
    messages = [{"role": "user", "content": context}]
    tools = [
        get_user_settings_tool_definition(),
        get_set_user_timezone_tool_definition(),
        get_nag_tool_definition(),
        get_delete_entry_tool_definition(),
    ]

    changes: list[str] = []
    for _ in range(RECONCILE_TURN_LIMIT):
        response = await _llm.beta.messages.create(
            model="claude-fable-5",
            max_tokens=OUTPUT_MAX_TOKENS,
            system=TRANSITION_PROMPT,
            messages=messages,
            tools=tools,
            betas=["server-side-fallback-2026-06-01"],
            fallbacks=[{"model": "claude-opus-4-8"}],
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            summary = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
            print(f"  agent summary: {summary}")
            return changes

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            call = f"{block.name}({json.dumps(block.input)})"
            print(f"  [tool call] {call}")
            try:
                content = await _execute_tool(block.name, block.input, phone_number)
                print(f"  [tool result] {content}")
                if block.name in MUTATING_TOOLS:
                    changes.append(call)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content,
                    }
                )
            except Exception as e:
                print(f"  [tool error] {e}")
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(e),
                        "is_error": True,
                    }
                )
        messages.append({"role": "user", "content": tool_results})

    print(f"  hit the {RECONCILE_TURN_LIMIT}-round cap without a final summary")
    return changes


async def main(target: str | None = None) -> None:
    all_numbers = await get_all_user_numbers()
    if target is not None:
        if target not in all_numbers:
            print(
                f"note: {target} has no message history on record — "
                "reconciling anyway (expect NO CHANGES)"
            )
        numbers = [target]
    else:
        numbers = all_numbers
    print(f"reconciling {len(numbers)} user(s): {', '.join(numbers)}")

    ledger: dict[str, list[str]] = {}
    for number in numbers:
        print(f"\n=== {number} ===")
        ledger[number] = await reconcile_user(number)

    print("\n" + "=" * 60)
    print("CHANGE LEDGER (state updates per user)")
    print("=" * 60)
    total = 0
    for number, changes in ledger.items():
        print(f"\n{number}: {len(changes)} change(s)")
        for change in changes:
            print(f"  - {change}")
        total += len(changes)
    print(f"\ntotal changes across all users: {total}")
    if total == 0:
        print("state is fully converged — nothing left to migrate.")


if __name__ == "__main__":
    import sys

    # python transition.py               -> reconcile every user
    # python transition.py +18323346991  -> reconcile just that one
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
