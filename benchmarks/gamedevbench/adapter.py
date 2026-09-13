"""GameDevBench command bridge; upstream runtime wiring is configured per environment."""

from mm_harness.runtimes.benchmark_command import CommandBenchmarkAdapter


class Adapter(CommandBenchmarkAdapter):
    benchmark = "gamedevbench"
