#!/usr/bin/env python
"""
Test Runner for Roger Intelligence Platform

Runs all test suites with configurable options:
- Unit tests
- Integration tests  
- Evaluation tests (LLM-as-Judge)
- Adversarial tests
- End-to-end tests

Usage:
    python run_tests.py                  # Run all tests
    python run_tests.py --unit           # Run unit tests only
    python run_tests.py --eval           # Run evaluation tests only
    python run_tests.py --adversarial    # Run adversarial tests only
    python run_tests.py --with-langsmith # Enable LangSmith tracing
"""
import argparse
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime


PROJECT_ROOT = Path(__file__).parent
TESTS_DIR = PROJECT_ROOT / "tests"


def run_pytest(args: list, verbose: bool = True) -> int:
    """Run pytest with given arguments."""
    cmd = ["pytest"] + args
    if verbose:
        cmd.append("-v")
    
    print(f"\n{'='*60}")
    print(f"Running: {' '.join(cmd)}")
    print(f"{'='*60}\n")
    
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return result.returncode


def run_all_tests(with_coverage: bool = False, with_langsmith: bool = False) -> int:
    """Run all test suites."""
    args = [str(TESTS_DIR)]
    
    if with_coverage:
        args.extend(["--cov=src", "--cov-report=html", "--cov-report=term"])
    
    if with_langsmith:
        os.environ["LANGSMITH_TRACING_TESTS"] = "true"
    
    return run_pytest(args)


def run_unit_tests() -> int:
    """Run unit tests only."""
    return run_pytest([str(TESTS_DIR / "unit"), "-m", "not slow"])


def run_integration_tests() -> int:
    """Run integration tests."""
    return run_pytest([str(TESTS_DIR / "integration"), "-m", "integration"])


def run_evaluation_tests(with_langsmith: bool = True) -> int:
    """Run LLM-as-Judge evaluation tests."""
    if with_langsmith:
        os.environ["LANGSMITH_TRACING_TESTS"] = "true"
    return run_pytest([str(TESTS_DIR / "evaluation"), "-m", "evaluation", "--tb=short"])


def run_adversarial_tests() -> int:
    """Run adversarial/security tests."""
    return run_pytest([str(TESTS_DIR / "evaluation" / "adversarial_tests.py"), "-m", "adversarial", "--tb=short"])


def run_e2e_tests() -> int:
    """Run end-to-end tests."""
    return run_pytest([str(TESTS_DIR / "e2e"), "-m", "e2e", "--tb=long"])


def run_evaluator_standalone():
    """Run the standalone agent evaluator."""
    from tests.evaluation.agent_evaluator import run_evaluation_cli
    return run_evaluation_cli()


def main():
    parser = argparse.ArgumentParser(description="Roger Intelligence Platform Test Runner")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    parser.add_argument("--unit", action="store_true", help="Run unit tests only")
    parser.add_argument("--integration", action="store_true", help="Run integration tests")
    parser.add_argument("--eval", action="store_true", help="Run evaluation tests")
    parser.add_argument("--adversarial", action="store_true", help="Run adversarial tests")
    parser.add_argument("--e2e", action="store_true", help="Run end-to-end tests")
    parser.add_argument("--evaluator", action="store_true", help="Run standalone evaluator")
    parser.add_argument("--coverage", action="store_true", help="Generate coverage report")
    parser.add_argument("--with-langsmith", action="store_true", help="Enable LangSmith tracing")
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("ROGER INTELLIGENCE PLATFORM - TEST RUNNER")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)
    
    exit_code = 0
    
    if args.with_langsmith:
        os.environ["LANGSMITH_TRACING_TESTS"] = "true"
        print("[Config] LangSmith tracing ENABLED for tests")
    
    if args.evaluator:
        run_evaluator_standalone()
    elif args.unit:
        exit_code = run_unit_tests()
    elif args.integration:
        exit_code = run_integration_tests()
    elif args.eval:
        exit_code = run_evaluation_tests(args.with_langsmith)
    elif args.adversarial:
        exit_code = run_adversarial_tests()
    elif args.e2e:
        exit_code = run_e2e_tests()
    else:
        # Default: run all tests
        exit_code = run_all_tests(args.coverage, args.with_langsmith)
    
    print("\n" + "=" * 70)
    print(f"TEST RUN COMPLETE - Exit Code: {exit_code}")
    print("=" * 70)
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
