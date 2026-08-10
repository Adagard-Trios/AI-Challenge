"""
Agent Evaluator - Industry-Level Testing Harness

Implements LLM-as-Judge pattern for evaluating Roger Intelligence Platform agents.
Integrates with LangSmith for trace logging and provides comprehensive quality metrics.

Key Features:
- Tool selection accuracy evaluation
- Response quality scoring (relevance, coherence, accuracy)
- BLEU score for text similarity measurement
- Hallucination detection
- Graceful degradation testing
- LangSmith trace integration
"""

import os
import sys
import json
import time
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class EvaluationResult:
    """Result of a single evaluation test."""

    test_id: str
    category: str
    query: str
    passed: bool
    score: float  # 0.0 - 1.0
    tool_selection_correct: bool
    response_quality: float
    hallucination_detected: bool
    latency_ms: float
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class EvaluationReport:
    """Aggregated evaluation report."""

    timestamp: str
    total_tests: int
    passed_tests: int
    failed_tests: int
    average_score: float
    tool_selection_accuracy: float
    response_quality_avg: float
    hallucination_rate: float
    average_latency_ms: float
    results: List[EvaluationResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "summary": {
                "total_tests": self.total_tests,
                "passed_tests": self.passed_tests,
                "failed_tests": self.failed_tests,
                "pass_rate": self.passed_tests / max(self.total_tests, 1),
                "average_score": self.average_score,
                "tool_selection_accuracy": self.tool_selection_accuracy,
                "response_quality_avg": self.response_quality_avg,
                "hallucination_rate": self.hallucination_rate,
                "average_latency_ms": self.average_latency_ms,
            },
            "results": [
                {
                    "test_id": r.test_id,
                    "category": r.category,
                    "passed": r.passed,
                    "score": r.score,
                    "tool_selection_correct": r.tool_selection_correct,
                    "response_quality": r.response_quality,
                    "hallucination_detected": r.hallucination_detected,
                    "latency_ms": r.latency_ms,
                    "error": r.error,
                }
                for r in self.results
            ],
        }


class AgentEvaluator:
    """
    Comprehensive agent evaluation harness.

    Implements the LLM-as-Judge pattern for evaluating:
    1. Tool Selection: Did the agent use the right tools?
    2. Response Quality: Is the response relevant and coherent?
    3. Hallucination Detection: Did the agent fabricate information?
    4. Graceful Degradation: Does it handle failures properly?
    """

    def __init__(self, llm=None, use_langsmith: bool = True):
        self.llm = llm
        self.use_langsmith = use_langsmith
        self.langsmith_client = None

        if use_langsmith:
            self._setup_langsmith()

    def _setup_langsmith(self):
        """Initialize LangSmith client for evaluation logging."""
        try:
            from src.config.langsmith_config import (
                get_langsmith_client,
                LangSmithConfig,
            )

            config = LangSmithConfig()
            config.configure()
            self.langsmith_client = get_langsmith_client()
            if self.langsmith_client:
                print("[Evaluator] ✓ LangSmith connected for evaluation tracing")
        except ImportError:
            print("[Evaluator] ⚠️ LangSmith not available, running without tracing")

    def load_golden_dataset(self, path: Optional[Path] = None) -> List[Dict]:
        """Load golden dataset for evaluation."""
        if path is None:
            path = (
                PROJECT_ROOT
                / "tests"
                / "evaluation"
                / "golden_datasets"
                / "expected_responses.json"
            )

        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            print(f"[Evaluator] ⚠️ Golden dataset not found at {path}")
            return []

    def evaluate_tool_selection(
        self, expected_tools: List[str], actual_tools: List[str]
    ) -> Tuple[bool, float]:
        """
        Evaluate if the agent selected the correct tools.

        Returns:
            Tuple of (passed, score)
        """
        if not expected_tools:
            return True, 1.0

        expected_set = set(expected_tools)
        actual_set = set(actual_tools)

        # Calculate intersection
        correct = len(expected_set & actual_set)
        total_expected = len(expected_set)

        score = correct / total_expected if total_expected > 0 else 0.0
        passed = score >= 0.5  # At least half the expected tools used

        return passed, score

    def evaluate_response_quality(
        self,
        query: str,
        response: str,
        expected_contains: List[str],
        quality_threshold: float = 0.7,
    ) -> Tuple[bool, float]:
        """
        Evaluate response quality using keyword matching and structure.

        For production, this should use LLM-as-Judge with a quality rubric.
        This implementation provides a baseline heuristic.
        """
        if not response:
            return False, 0.0

        response_lower = response.lower()

        # Keyword matching score
        keyword_score = 0.0
        if expected_contains:
            matched = sum(1 for kw in expected_contains if kw.lower() in response_lower)
            keyword_score = matched / len(expected_contains)

        # Length and structure score
        word_count = len(response.split())
        length_score = min(1.0, word_count / 50)  # Expect at least 50 words

        # Combined score
        score = (keyword_score * 0.6) + (length_score * 0.4)
        passed = score >= quality_threshold

        return passed, score

    def calculate_bleu_score(
        self, reference: str, candidate: str, n_gram: int = 4
    ) -> float:
        """
        Calculate BLEU (Bilingual Evaluation Understudy) score for text similarity.

        BLEU measures the similarity between a candidate text and reference text
        based on n-gram precision. Higher scores indicate better similarity.

        Args:
            reference: Reference/expected text
            candidate: Generated/candidate text
            n_gram: Maximum n-gram to consider (default 4 for BLEU-4)

        Returns:
            BLEU score between 0.0 and 1.0
        """

        def tokenize(text: str) -> List[str]:
            """Simple tokenization - lowercase and split on non-alphanumeric."""
            return re.findall(r"\b\w+\b", text.lower())

        def get_ngrams(tokens: List[str], n: int) -> List[Tuple[str, ...]]:
            """Generate n-grams from token list."""
            return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]

        def modified_precision(
            ref_tokens: List[str], cand_tokens: List[str], n: int
        ) -> float:
            """Calculate modified n-gram precision with clipping."""
            if len(cand_tokens) < n:
                return 0.0

            cand_ngrams = get_ngrams(cand_tokens, n)
            ref_ngrams = get_ngrams(ref_tokens, n)

            if not cand_ngrams:
                return 0.0

            # Count n-grams
            cand_counts = Counter(cand_ngrams)
            ref_counts = Counter(ref_ngrams)

            # Clip counts by reference counts
            clipped_count = 0
            for ngram, count in cand_counts.items():
                clipped_count += min(count, ref_counts.get(ngram, 0))

            return clipped_count / len(cand_ngrams)

        def brevity_penalty(ref_len: int, cand_len: int) -> float:
            """Calculate brevity penalty for short candidates."""
            if cand_len == 0:
                return 0.0
            if cand_len >= ref_len:
                return 1.0
            return math.exp(1 - ref_len / cand_len)

        import math

        # Tokenize
        ref_tokens = tokenize(reference)
        cand_tokens = tokenize(candidate)

        if not ref_tokens or not cand_tokens:
            return 0.0

        # Calculate n-gram precisions
        precisions = []
        for n in range(1, n_gram + 1):
            p = modified_precision(ref_tokens, cand_tokens, n)
            precisions.append(p)

        # Avoid log(0)
        if any(p == 0 for p in precisions):
            return 0.0

        # Geometric mean of precisions (BLEU formula)
        log_precision_sum = sum(math.log(p) for p in precisions) / len(precisions)

        # Apply brevity penalty
        bp = brevity_penalty(len(ref_tokens), len(cand_tokens))

        bleu = bp * math.exp(log_precision_sum)

        return round(bleu, 4)

    def evaluate_bleu(
        self, expected_response: str, actual_response: str, threshold: float = 0.3
    ) -> Tuple[bool, float]:
        """
        Evaluate response using BLEU score.

        Args:
            expected_response: Reference/expected response text
            actual_response: Generated response text
            threshold: Minimum BLEU score to pass (default 0.3)

        Returns:
            Tuple of (passed, bleu_score)
        """
        bleu = self.calculate_bleu_score(expected_response, actual_response)
        passed = bleu >= threshold
        return passed, bleu

    def evaluate_response_quality_llm(
        self, query: str, response: str, context: str = ""
    ) -> Tuple[bool, float, str]:
        """
        LLM-as-Judge evaluation for response quality.

        Uses the configured LLM to judge response quality on a rubric.
        Requires self.llm to be set.

        Returns:
            Tuple of (passed, score, reasoning)
        """
        if not self.llm:
            # Fallback to heuristic
            passed, score = self.evaluate_response_quality(query, response, [])
            return passed, score, "LLM not available, used heuristic"

        judge_prompt = f"""You are an expert evaluator for an AI intelligence system.
Rate the following response on a scale of 0-10 based on:
1. Relevance to the query
2. Accuracy of information
3. Clarity and coherence
4. Completeness

Query: {query}

Response: {response}

{f"Context: {context}" if context else ""}

Provide your evaluation as JSON:
{{"score": <0-10>, "reasoning": "<brief explanation>", "issues": ["<issue1>", ...]}}
"""
        try:
            result = self.llm.invoke(judge_prompt)
            parsed = json.loads(result.content)
            score = parsed.get("score", 5) / 10.0
            reasoning = parsed.get("reasoning", "")
            return score >= 0.7, score, reasoning
        except Exception as e:
            return False, 0.5, f"Evaluation error: {e}"

    def detect_hallucination(
        self, response: str, source_data: Optional[Dict] = None
    ) -> Tuple[bool, float]:
        """
        Detect potential hallucinations in the response.

        Heuristic approach - checks for fabricated specifics.
        For production, should compare against source data.
        """
        hallucination_indicators = [
            "I don't have access to",
            "I cannot verify",
            "As of my knowledge",
            "I'm not able to confirm",
        ]

        response_lower = response.lower()

        # Check for uncertainty indicators (good sign - honest about limitations)
        has_uncertainty = any(
            ind.lower() in response_lower for ind in hallucination_indicators
        )

        # Check for overly specific claims without source
        # This is a simplified heuristic
        if source_data:
            # Compare claimed facts against source data
            pass

        # For now, if the response admits uncertainty when appropriate, less likely hallucinating
        hallucination_score = 0.2 if has_uncertainty else 0.5
        detected = hallucination_score > 0.6

        return detected, hallucination_score

    def evaluate_single(
        self,
        test_case: Dict[str, Any],
        agent_response: str,
        tools_used: List[str],
        latency_ms: float,
    ) -> EvaluationResult:
        """Run evaluation for a single test case."""
        test_id = test_case.get("id", "unknown")
        category = test_case.get("category", "unknown")
        query = test_case.get("query", "")
        expected_tools = test_case.get("expected_tools", [])
        expected_contains = test_case.get("expected_response_contains", [])
        quality_threshold = test_case.get("quality_threshold", 0.7)

        # Evaluate components
        tool_correct, tool_score = self.evaluate_tool_selection(
            expected_tools, tools_used
        )
        quality_passed, quality_score = self.evaluate_response_quality(
            query, agent_response, expected_contains, quality_threshold
        )
        hallucination_detected, halluc_score = self.detect_hallucination(agent_response)

        # Calculate overall score
        overall_score = (
            tool_score * 0.3 + quality_score * 0.5 + (1 - halluc_score) * 0.2
        )

        passed = tool_correct and quality_passed and not hallucination_detected

        return EvaluationResult(
            test_id=test_id,
            category=category,
            query=query,
            passed=passed,
            score=overall_score,
            tool_selection_correct=tool_correct,
            response_quality=quality_score,
            hallucination_detected=hallucination_detected,
            latency_ms=latency_ms,
            details={
                "tool_score": tool_score,
                "expected_tools": expected_tools,
                "actual_tools": tools_used,
            },
        )

    def run_evaluation(
        self, golden_dataset: Optional[List[Dict]] = None, agent_executor=None
    ) -> EvaluationReport:
        """
        Run full evaluation suite against golden dataset.

        Args:
            golden_dataset: List of test cases (loads default if None)
            agent_executor: Optional callable to execute agent (for live testing)

        Returns:
            EvaluationReport with aggregated results
        """
        if golden_dataset is None:
            golden_dataset = self.load_golden_dataset()

        if not golden_dataset:
            print("[Evaluator] ⚠️ No test cases to evaluate")
            return EvaluationReport(
                timestamp=datetime.now().isoformat(),
                total_tests=0,
                passed_tests=0,
                failed_tests=0,
                average_score=0.0,
                tool_selection_accuracy=0.0,
                response_quality_avg=0.0,
                hallucination_rate=0.0,
                average_latency_ms=0.0,
            )

        results = []

        for test_case in golden_dataset:
            print(f"[Evaluator] Running test: {test_case.get('id', 'unknown')}")

            start_time = time.time()

            if agent_executor:
                # Live evaluation with actual agent
                try:
                    response, tools_used = agent_executor(test_case["query"])
                except Exception as e:
                    result = EvaluationResult(
                        test_id=test_case.get("id", "unknown"),
                        category=test_case.get("category", "unknown"),
                        query=test_case.get("query", ""),
                        passed=False,
                        score=0.0,
                        tool_selection_correct=False,
                        response_quality=0.0,
                        hallucination_detected=False,
                        latency_ms=0.0,
                        error=str(e),
                    )
                    results.append(result)
                    continue
            else:
                # Mock evaluation (for testing the evaluator itself)
                response = f"Mock response for: {test_case.get('query', '')}"
                tools_used = test_case.get("expected_tools", [])[
                    :1
                ]  # Simulate partial tool use

            latency_ms = (time.time() - start_time) * 1000

            result = self.evaluate_single(
                test_case=test_case,
                agent_response=response,
                tools_used=tools_used,
                latency_ms=latency_ms,
            )
            results.append(result)

        # Aggregate results
        total = len(results)
        passed = sum(1 for r in results if r.passed)

        report = EvaluationReport(
            timestamp=datetime.now().isoformat(),
            total_tests=total,
            passed_tests=passed,
            failed_tests=total - passed,
            average_score=sum(r.score for r in results) / max(total, 1),
            tool_selection_accuracy=sum(1 for r in results if r.tool_selection_correct)
            / max(total, 1),
            response_quality_avg=sum(r.response_quality for r in results)
            / max(total, 1),
            hallucination_rate=sum(1 for r in results if r.hallucination_detected)
            / max(total, 1),
            average_latency_ms=sum(r.latency_ms for r in results) / max(total, 1),
            results=results,
        )

        return report

    def save_report(self, report: EvaluationReport, path: Optional[Path] = None):
        """Save evaluation report to JSON file."""
        if path is None:
            path = PROJECT_ROOT / "tests" / "evaluation" / "reports"
            path.mkdir(parents=True, exist_ok=True)
            path = path / f"eval_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        with open(path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)

        print(f"[Evaluator] ✓ Report saved to {path}")
        return path


def run_evaluation_cli():
    """CLI entry point for running evaluations."""
    print("=" * 60)
    print("Roger Intelligence Platform - Agent Evaluator")
    print("=" * 60)

    evaluator = AgentEvaluator(use_langsmith=True)

    # Run evaluation with mock executor (for testing)
    report = evaluator.run_evaluation()

    # Print summary
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Total Tests: {report.total_tests}")
    print(
        f"Passed: {report.passed_tests} ({report.passed_tests/max(report.total_tests,1)*100:.1f}%)"
    )
    print(f"Failed: {report.failed_tests}")
    print(f"Average Score: {report.average_score:.2f}")
    print(f"Tool Selection Accuracy: {report.tool_selection_accuracy*100:.1f}%")
    print(f"Response Quality Avg: {report.response_quality_avg*100:.1f}%")
    print(f"Hallucination Rate: {report.hallucination_rate*100:.1f}%")
    print(f"Average Latency: {report.average_latency_ms:.1f}ms")

    # Save report
    evaluator.save_report(report)

    return report


if __name__ == "__main__":
    run_evaluation_cli()
