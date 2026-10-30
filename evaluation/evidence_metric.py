"""Optional DeepEval metric with no LLM judge or cloud data transfer."""
import re
import os

os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"

from deepeval.metrics import BaseMetric


class EvidenceCitationMetric(BaseMetric):
    def __init__(self, threshold=1.0):
        self.threshold = threshold
        self.score = 0.0
        self.reason = ""

    def measure(self, test_case, *args, **kwargs):
        answer = test_case.actual_output or ""
        sources = test_case.retrieval_context or []
        citations = [int(n) for n in re.findall(r"\[(\d+)\]", answer)]
        self.score = float(bool(citations) and all(1 <= n <= len(sources) for n in citations))
        self.success = self.score >= self.threshold
        self.reason = "Citation IDs resolve to retrieved evidence." if self.success else "Missing or out-of-range citations."
        return self.score

    async def a_measure(self, test_case, *args, **kwargs):
        return self.measure(test_case)

    def is_successful(self):
        return self.score >= self.threshold

    @property
    def __name__(self):
        return "Evidence citation validity (does not certify factual correctness)"


if __name__ == "__main__":
    from deepeval.test_case import LLMTestCase
    metric = EvidenceCitationMetric()
    example = LLMTestCase(input="When is a refund processed?", actual_output="Within five business days. [1]", retrieval_context=["Refunds are processed within five business days."])
    print({"score": metric.measure(example), "passed": metric.is_successful(), "reason": metric.reason})
