"""Research portfolio separate from historical adapter configuration dictionaries."""

from dataclasses import asdict, dataclass

from .mechanisms import MM_STAGES, MODALITIES

PORTFOLIO_STATUSES = ("active", "archived", "legacy_smoke", "reserve", "reserve_transfer")
INTEGRATION_STATUSES = (
    "planned",
    "source_integrated",
    "smoke_validated",
    "rollout_validated",
    "scoring_validated",
    "evolution_validated",
)


@dataclass(frozen=True)
class BenchmarkMechanismProfile:
    benchmark_id: str
    status: str
    task_domain: str
    modalities: list[str]
    environment_type: str
    initial_media_available: bool | None
    active_observation_available: bool | None
    interactive_environment: bool | None
    applicable_mm_stages: list[str]
    current_h0_harness: str
    current_h0_media_policy: str
    agent_visible_media: list[str]
    evaluator_only_media: list[str]
    development_data_status: str
    heldout_evaluation_status: str
    known_generic_failure_evidence: list[str]
    known_mm_failure_evidence: list[str]
    mechanism_headroom: str
    integration_status: str
    integration_evidence: list[str]
    limitations: list[str]
    mutation_boundary: str
    source_lock: str | None = None
    schema: str = "benchmark-mechanism-profile/v1"

    def __post_init__(self):
        if (
            self.status not in PORTFOLIO_STATUSES
            or self.integration_status not in INTEGRATION_STATUSES
        ):
            raise ValueError("Unknown portfolio/integration status")
        if self.mechanism_headroom not in {"confirmed", "plausible", "unsupported", "unknown"}:
            raise ValueError("Unknown mechanism headroom")
        if any(s not in MM_STAGES for s in self.applicable_mm_stages) or any(
            m not in MODALITIES for m in self.modalities
        ):
            raise ValueError("Invalid stages/modalities")
        if self.integration_status != "planned" and not self.integration_evidence:
            raise ValueError("Integration claims require explicit evidence")
        if self.mechanism_headroom == "confirmed" and not self.known_mm_failure_evidence:
            raise ValueError("Confirmed MM headroom needs real MM failure evidence")

    def to_dict(self):
        return asdict(self)
