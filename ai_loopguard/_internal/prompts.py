"""Default escalation prompt templates.

The default prompt tells the escalation model what went wrong and
asks it to break the loop. Users can override via GuardConfig.

Prompts live in _internal because they are an implementation detail
of escalation — not a public API contract.  Users can supply custom
prompts via GuardConfig.escalation_prompt, but the default template
format and field names are not part of loopguard's semver guarantees.
"""

# Uses f-string fields from EscalationContext._to_prompt_kwargs().
# The .format()-style {placeholders} deliberately match dict keys
# produced by _to_prompt_kwargs() so that a single call to
# prompt.format(**context._to_prompt_kwargs()) fills all fields.
# Fields that would be empty (e.g., last_error when no error occurred)
# are the responsibility of _to_prompt_kwargs() to supply a sensible
# default like "None" or "N/A".
DEFAULT_ESCALATION_PROMPT = """\
You are an escalation model. A less capable model was working on a task and got stuck \
in a loop. Your job is to break the cycle and produce a working result.

## What happened
- Trigger: {trigger_type} — {trigger_detail}
- Retries attempted: {retry_count}
- Workhorse model: {workhorse_model}

## What was tried
{failed_attempts}

## Last error
{last_error}

## Your task
Analyse why the previous model got stuck. Then produce the correct output \
that resolves the task. Do not repeat the same approach that failed.
"""
