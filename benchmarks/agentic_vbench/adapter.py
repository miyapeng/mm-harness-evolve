"""Source-integrated only; command transport is intentionally unconfigured."""

from mm_harness.runtimes.benchmark_command import CommandBenchmarkAdapter


class Adapter(CommandBenchmarkAdapter):
    benchmark = "agentic_vbench"
