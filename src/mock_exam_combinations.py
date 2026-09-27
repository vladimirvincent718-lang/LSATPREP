"""Combinatoric estimates for distinct mock-exam question sets."""
import math


def possible_mock_exams(question_count: int, questions_per_mock: int) -> int:
    """Return n-choose-k; question order does not create another exam."""
    n, k = int(question_count), int(questions_per_mock)
    if n < 0 or k < 1 or k > n:
        return 0
    return math.comb(n, k)


def non_overlapping_mock_exams(question_count: int, questions_per_mock: int) -> int:
    """Return how many complete mocks can be made without reusing a question."""
    n, k = int(question_count), int(questions_per_mock)
    return n // k if n >= 0 and k > 0 else 0


def compact_combination_count(value: int) -> str:
    """Describe huge totals without scientific notation."""
    value = int(value)
    if value < 1_000_000_000_000:
        return f"{value:,}"
    return f"{len(str(value))}-digit total"


def metric_drilldown_script() -> str:
    """Make the Possible Mocks metric open its hidden settings button."""
    return """<script>
    (function bindMockEstimateCard() {
      var doc = window.parent && window.parent.document;
      if (!doc) return;
      var anchor = doc.getElementById('sf-mock-estimate-anchor');
      var column = anchor && anchor.closest('[data-testid="stColumn"]');
      var metric = column && column.querySelector('[data-testid="stMetric"]');
      var button = column && Array.from(column.querySelectorAll('button')).find(function (item) {
        return (item.textContent || '').indexOf('Open mock estimate settings') !== -1;
      });
      if (!metric || !button) {
        window.setTimeout(bindMockEstimateCard, 100);
        return;
      }
      metric.title = 'Double-click to adjust estimated bank size and questions per mock';
      metric.setAttribute('aria-description', metric.title);
      metric.style.cursor = 'pointer';
      if (metric.dataset.sfMockEstimateBound === '1') return;
      metric.dataset.sfMockEstimateBound = '1';
      metric.addEventListener('dblclick', function () { button.click(); });
    })();
    </script>"""
