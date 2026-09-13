"""Claw-Eval-MM command bridge; native workers are wired in its own environment."""

from mm_harness.runtimes.benchmark_command import CommandBenchmarkAdapter


class Adapter(CommandBenchmarkAdapter):
    benchmark = "claw_eval_mm"
