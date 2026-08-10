"""Typed hand-off contracts between agents.

The whole system rests on this file. Agents never pass prose to each other —
each one emits a schema-validated artifact that the next one consumes. The
schemas are also fed to the Messages API as `output_config.format`, so a
malformed hand-off is rejected by the API before it ever reaches our code.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"


# --------------------------------------------------------------------------
# 0. Intake -> a plain-language understanding, confirmed by the human
# --------------------------------------------------------------------------


class Clarification(BaseModel):
    """A question the request leaves open, with the answer we intend to assume.

    Asking a non-technical user three open questions and waiting stalls them.
    Asking a question *and* proposing an answer lets them confirm in one click
    and correct only what is wrong.
    """

    question: str = Field(description="In the user's own everyday words. No jargon.")
    assumed_answer: str = Field(
        description="What we will assume if the user does not say otherwise."
    )
    why_it_matters: str = Field(
        description="One sentence on what changes depending on the answer."
    )


class IntakeBrief(BaseModel):
    """What the crew believes the user wants, in the user's own language."""

    understood_goal: str = Field(
        description="'If I understood correctly, you want ...' — one or two sentences, "
        "no technical vocabulary, in the same language the user wrote in."
    )
    proposed_steps: list[str] = Field(
        description="What will be done, in plain language a non-developer can judge. "
        "Three to six steps, each one a visible outcome rather than a code change."
    )
    clarifications: list[Clarification] = Field(
        description="Two or three at most. Empty when the request is genuinely unambiguous."
    )
    out_of_scope: list[str] = Field(
        description="Adjacent things explicitly not being done, in plain language."
    )
    risk_note: str = Field(
        description="What could go wrong, and whether it is reversible. Plain language."
    )
    technical_request: str = Field(
        description="The same request rewritten for the engineering team: precise, "
        "unambiguous, in English. This is what the analyst receives — the plain-language "
        "fields above are for the human."
    )


# --------------------------------------------------------------------------
# 1. Business Analyst -> functional specification
# --------------------------------------------------------------------------


class UserStory(BaseModel):
    id: str = Field(description="Stable slug, e.g. 'US-1'.")
    as_a: str = Field(description="The actor. 'an unauthenticated visitor'.")
    i_want: str = Field(description="The capability, in the actor's words.")
    so_that: str = Field(description="The business value obtained.")
    acceptance_criteria: list[str] = Field(
        description="Observable, testable conditions. Each must be checkable by a "
        "test or a manual step — never 'works well'."
    )


class Spec(BaseModel):
    """What the user actually asked for, restated unambiguously."""

    summary: str = Field(description="Two sentences max, plain language.")
    user_stories: list[UserStory]
    out_of_scope: list[str] = Field(
        description="Explicitly excluded work. Prevents downstream scope creep."
    )
    open_questions: list[str] = Field(
        description="Ambiguities that would change the work materially if resolved "
        "differently. Empty when the request is unambiguous."
    )
    assumptions: list[str] = Field(
        description="Decisions taken to move forward despite an open question."
    )


# --------------------------------------------------------------------------
# 2. Software Architect -> technical plan
# --------------------------------------------------------------------------


class PlanAction(str, Enum):
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"
    INSTALL = "install"
    CONFIGURE = "configure"


class PlanStep(BaseModel):
    id: str = Field(description="Stable slug, e.g. 'S-1'.")
    action: PlanAction
    target: str = Field(
        description="Workspace-relative file path, or the package name for 'install'."
    )
    intent: str = Field(description="What this step must achieve, not how to type it.")
    rationale: str = Field(description="Why this location and this approach.")
    depends_on: list[str] = Field(
        default_factory=list, description="Ids of steps that must land first."
    )
    covers: list[str] = Field(
        default_factory=list,
        description="User story ids this step contributes to. Used to prove coverage.",
    )


class Risk(BaseModel):
    description: str
    severity: Severity
    mitigation: str


class Plan(BaseModel):
    """How the change will be made, decided before a single line is written."""

    approach: str = Field(description="The chosen design, in a short paragraph.")
    alternatives_rejected: list[str] = Field(
        description="Designs considered and dropped, with the reason. This is the "
        "decision log a reviewer actually reads."
    )
    steps: list[PlanStep]
    risks: list[Risk]
    verification_strategy: str = Field(
        description="How QA will know this worked: which tests, which commands."
    )


# --------------------------------------------------------------------------
# 3. Developer -> changeset
# --------------------------------------------------------------------------


class FileChange(BaseModel):
    path: str
    action: PlanAction
    summary: str = Field(description="One line: what changed in this file and why.")


class ChangeSet(BaseModel):
    """What the developer actually did — reconciled against the plan by QA."""

    summary: str
    files_changed: list[FileChange]
    commands_run: list[str] = Field(default_factory=list)
    steps_completed: list[str] = Field(description="Plan step ids that are done.")
    steps_skipped: list[str] = Field(
        default_factory=list, description="Plan step ids deliberately not done."
    )
    skip_reasons: list[str] = Field(
        default_factory=list, description="One reason per skipped step, same order."
    )
    notes_for_qa: str = Field(
        default="", description="Anything QA should look at first."
    )


# --------------------------------------------------------------------------
# 4. QA -> report
# --------------------------------------------------------------------------


class CheckResult(BaseModel):
    name: str = Field(description="e.g. 'pytest', 'ruff', 'secret-scan'.")
    passed: bool
    detail: str = Field(description="Command output digest, or why it was skipped.")


class Finding(BaseModel):
    severity: Severity
    file: str = Field(default="", description="Workspace-relative path, if localised.")
    line: int = Field(default=0, description="1-indexed; 0 when not line-specific.")
    summary: str = Field(description="One sentence stating the defect.")
    failure_scenario: str = Field(
        description="Concrete inputs or state that produce the wrong behaviour. "
        "A finding without one is speculation, not a defect."
    )
    suggested_fix: str


class QAReport(BaseModel):
    """The gate. A 'fail' verdict sends work back to the developer."""

    verdict: Verdict
    checks: list[CheckResult]
    findings: list[Finding] = Field(
        default_factory=list, description="Empty when the verdict is 'pass'."
    )
    uncovered_stories: list[str] = Field(
        default_factory=list,
        description="User story ids with no evidence of implementation.",
    )
    summary: str


# --------------------------------------------------------------------------
# 5. Documentation Writer -> docs bundle
# --------------------------------------------------------------------------


class HumanReport(BaseModel):
    """The end-of-run report for someone who will not read a diff.

    Three questions, in the user's own language: what changed, how do we know
    it works, and what should I keep an eye on.
    """

    what_changed: str = Field(
        description="What the software does now that it did not before, described as "
        "behaviour a user would notice — not as files or functions."
    )
    what_was_verified: str = Field(
        description="What was actually checked and how: which tests ran, what they "
        "prove. Say plainly if something was not verified."
    )
    what_to_watch: str = Field(
        description="What remains, what could go wrong, what a human should review. "
        "'Nothing' is an acceptable answer when it is true."
    )


class DocsBundle(BaseModel):
    changelog_entry: str = Field(description="Keep-a-Changelog style markdown block.")
    api_documentation: str = Field(
        default="", description="Markdown for new or changed endpoints. May be empty."
    )
    usage_examples: str = Field(default="", description="Runnable examples, markdown.")
    setup_instructions: str = Field(
        default="", description="Only the steps that changed. Empty when nothing did."
    )
    summary_for_humans: str = Field(
        description="The paragraph a teammate reads to understand the whole change."
    )
    plain_language_diff: str = Field(
        description="The diff explained to someone who cannot read a diff, in the "
        "language the user wrote in. Two or three sentences: what was added or "
        "changed, and explicitly whether any existing behaviour changed."
    )
    report: HumanReport


# --------------------------------------------------------------------------
# Registry + JSON Schema conversion for the Messages API
# --------------------------------------------------------------------------

ARTIFACT_MODELS: dict[str, type[BaseModel]] = {
    "intake": IntakeBrief,
    "spec": Spec,
    "plan": Plan,
    "changeset": ChangeSet,
    "qa_report": QAReport,
    "docs_bundle": DocsBundle,
}


def _harden(node: Any) -> Any:
    """Make a Pydantic JSON Schema acceptable to Anthropic structured outputs.

    Two API requirements Pydantic does not emit on its own: every object must
    set `additionalProperties: false`, and every property must be listed in
    `required`. Constraints the API does not support (minLength, minimum, ...)
    are dropped — Pydantic still enforces them locally on parse.
    """
    unsupported = {
        "minLength", "maxLength", "pattern", "format",
        "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
        "minItems", "maxItems", "uniqueItems",
    }
    if isinstance(node, dict):
        out = {k: _harden(v) for k, v in node.items() if k not in unsupported}
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"].keys())
        # Defaults imply optionality, which conflicts with "everything required".
        out.pop("default", None)
        return out
    if isinstance(node, list):
        return [_harden(item) for item in node]
    return node


def json_schema_for(model: type[BaseModel]) -> dict[str, Any]:
    """The `output_config.format.schema` payload for a given artifact model."""
    return _harden(model.model_json_schema())


def output_format_for(model: type[BaseModel]) -> dict[str, Any]:
    return {"type": "json_schema", "schema": json_schema_for(model)}


__all__ = [
    "ARTIFACT_MODELS", "ChangeSet", "Clarification", "CheckResult", "DocsBundle",
    "FileChange", "Finding", "HumanReport", "IntakeBrief", "Plan", "PlanAction",
    "PlanStep", "QAReport", "Risk", "Severity", "Spec", "UserStory", "Verdict",
    "json_schema_for", "output_format_for",
]
