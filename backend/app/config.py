"""Runtime configuration.

Every hard limit the crew runs under lives here. They are ceilings, not hints:
the orchestrator stops and escalates rather than quietly exceeding one.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class LLMProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai_compatible"  # llama.cpp, vLLM, SGLang, LM Studio
    FAKE = "fake"


class ApprovalMode(str, Enum):
    """How much the crew asks before acting.

    The middle setting is the useful one, and it rests on a criterion that can
    be checked rather than argued about: a run works on its own git branch from
    a recorded commit, so anything git can undo is *reversible*. Editing a file
    is. Running `pip install`, or any command reaching the network, is not —
    its effects live outside the branch.
    """

    ASK = "ask"        # every write, command and commit
    RISKY = "risky"    # only what a git reset cannot undo
    AUTO = "auto"      # nothing; the run still escalates when it hits a limit

    @property
    def label(self) -> str:
        return {
            ApprovalMode.ASK: "Ask me about everything",
            ApprovalMode.RISKY: "Ask me only when it cannot be undone",
            ApprovalMode.AUTO: "Go ahead, tell me if you get stuck",
        }[self]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    llm_provider: LLMProvider = LLMProvider.ANTHROPIC

    # OpenAI-compatible provider (a local llama.cpp / vLLM / SGLang server).
    # Accepts several comma-separated URLs. They must all serve the same model:
    # a run whose turns landed on different models would be a mixture nobody
    # could reason about, and every benchmark comparison across it would be
    # measuring the routing. `/api/health` reports disagreement.
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    # A second server running a *different* model, given to specific roles.
    # This is the opposite case from the list above: those servers must be
    # interchangeable, these deliberately are not. A small model is cheap and
    # fast on mechanical work, so pointing the documenter at one frees the big
    # model for the phases that need it — whether that trade is worth making
    # is a benchmark question, not an assumption.
    #   OPENAI_ROLE_ENDPOINTS=documenter=http://host:30001/v1|small-model.gguf
    openai_role_endpoints: str = ""
    # Qwen3-family reasoning toggle, passed as chat_template_kwargs.
    openai_enable_thinking: bool = True
    # The server's configured context window. Output budgets are capped from it.
    openai_max_context_tokens: int = 65_536

    # Decoding. Left unset, the server applies its own random defaults — three
    # identical requests returned three different plans, which is most of the
    # run-to-run variance this project spent an afternoon measuring.
    # `temperature=0` made them byte-identical. Production keeps the model's
    # recommended sampling (Qwen3 wants ~0.7 for reasoning); benchmarks pin it
    # to 0 so a comparison measures the change and not the dice.
    openai_temperature: float | None = None
    openai_top_p: float | None = None
    openai_top_k: int | None = None
    openai_seed: int | None = None

    model_orchestrator: str = "claude-opus-5"
    model_translator: str = "claude-sonnet-5"
    model_analyst: str = "claude-sonnet-5"
    model_architect: str = "claude-opus-5"
    model_developer: str = "claude-sonnet-5"
    model_qa: str = "claude-sonnet-5"
    model_documenter: str = "claude-haiku-4-5"

    # Off by default because nothing showed it helps. Injecting a static map of
    # the repository into every system prompt was expected to save the
    # exploration tool calls the benchmark had shown agents spending. Summed
    # over the four tasks it came out worse — 240 tool calls against 181,
    # 2.36M tokens against 1.49M, same number of passes — but that was one run
    # per task, and `--compare` classes every row `unrepeated`: with no
    # repetitions there are no ranges to fail to overlap. So the claim is not
    # "the map costs more", it is "there is no evidence it helps", which is
    # still enough to keep the default at the setting that changes nothing.
    # Worth re-measuring under `--repeat 3` and greedy decoding.
    repo_map_enabled: bool = False

    # Intake turns a non-developer's problem statement into a precise request
    # and confirms it before any work starts. Turn it off when requests already
    # arrive precise — a benchmark task, or a call from another program.
    intake_enabled: bool = True
    max_intake_rounds: int = 3

    max_qa_iterations: int = 3
    max_tokens_per_run: int = 400_000
    max_wall_clock_seconds: int = 900
    max_tool_calls_per_agent: int = 40

    # Where the crew actually works. Provisioned by copying workspace_template,
    # so the committed demo repo is never mutated.
    workspace_root: Path = REPO_ROOT / "data" / "workspace"
    # Set to None (or an empty string in .env) to work in workspace_root as-is,
    # which is what you want when pointing at a real project of your own.
    workspace_template: Path | None = REPO_ROOT / "demo-repo"
    # One git worktree per run: runs stop sharing a working tree, so they can
    # overlap, and discarding one becomes a delete rather than a revert.
    use_worktrees: bool = True
    # Working on a repository you care about is opt-in: the crew branches and
    # commits there, so it must never happen by leaving a path misconfigured.
    allow_external_workspace: bool = False

    approval_mode: ApprovalMode = ApprovalMode.ASK
    database_path: Path = REPO_ROOT / "data" / "runs.db"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator("workspace_root", "database_path", mode="after")
    @classmethod
    def _absolute(cls, value: Path) -> Path:
        return value if value.is_absolute() else (REPO_ROOT / value).resolve()

    @field_validator("workspace_template", mode="after")
    @classmethod
    def _optional_absolute(cls, value: Path | None) -> Path | None:
        if value is None or not str(value).strip():
            return None
        return value if value.is_absolute() else (REPO_ROOT / value).resolve()

    @property
    def openai_base_urls(self) -> list[str]:
        """One entry per model server, in the order configured, deduplicated."""
        seen: dict[str, None] = {}
        for raw in self.openai_base_url.split(","):
            url = raw.strip().rstrip("/")
            if url:
                seen.setdefault(url, None)
        return list(seen)

    @property
    def openai_role_routes(self) -> dict[str, tuple[str, str]]:
        """role -> (url, model), parsed from `role=url|model` entries.

        `|` separates the model rather than `:` or `/`, both of which appear in
        a URL. The model is required: a server that is only reachable under the
        exact name it reports would 404 on the other server's name, and
        discovering that mid-run is worse than refusing at startup.
        """
        routes: dict[str, tuple[str, str]] = {}
        for entry in self.openai_role_endpoints.split(","):
            entry = entry.strip()
            if not entry:
                continue
            role, _, target = entry.partition("=")
            url, _, model = target.partition("|")
            if not (role.strip() and url.strip() and model.strip()):
                raise ValueError(
                    f"OPENAI_ROLE_ENDPOINTS entry {entry!r} is not "
                    "'role=url|model' — the model name is required"
                )
            routes[role.strip().lower()] = (url.strip().rstrip("/"), model.strip())
        return routes

    @property
    def effective_provider(self) -> LLMProvider:
        """Fall back to the fake provider rather than fail at request time.

        A missing key or base URL is a configuration mistake, and discovering it
        when the first agent runs — halfway through a run, after the workspace
        has been branched — is worse than discovering it at startup.
        """
        if self.llm_provider is LLMProvider.ANTHROPIC and not self.anthropic_api_key:
            return LLMProvider.FAKE
        if self.llm_provider is LLMProvider.OPENAI_COMPATIBLE and not (
            self.openai_base_url and self.openai_model
        ):
            return LLMProvider.FAKE
        return self.llm_provider


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Test hook — forces the next get_settings() to re-read the environment."""
    global _settings
    _settings = None
