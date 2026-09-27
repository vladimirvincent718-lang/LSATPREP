"""Professional-context preferences for StudyForge practice sessions.

The specialty adds a job-relevant interpretation cue while the canonical
question, choices, answer key, and explanation remain unchanged.
"""

from __future__ import annotations


PROFESSIONAL_SPECIALTY_SETTING = "professional_specialty"
DEFAULT_SPECIALTY = "standard"

SPECIALTY_LABELS = {
    DEFAULT_SPECIALTY: "Standard CFA context",
    "restaurant_hospitality": "Restaurant & Hospitality",
    "fitness_wellness": "Fitness & Wellness",
    "technology_saas": "Technology & SaaS",
    "real_estate": "Real Estate",
    "healthcare": "Healthcare",
    "banking_financial_services": "Banking & Financial Services",
}

SPECIALTY_OPTIONS = tuple(SPECIALTY_LABELS)

_ROLE_CONTEXTS = {
    "restaurant_hospitality": "a finance professional supporting a multi-location restaurant or hospitality operator",
    "fitness_wellness": "a finance professional supporting a gym, studio, or wellness business",
    "technology_saas": "a finance professional supporting a technology or subscription-software company",
    "real_estate": "a finance professional evaluating property operations and investment decisions",
    "healthcare": "a finance professional supporting a healthcare provider or services organization",
    "banking_financial_services": "a finance professional working with a bank or financial-services firm",
}

_MODULE_ACTIONS = (
    (("ethic", "standard"), "consider how professional duties and conflicts should guide the decision"),
    (("quant", "statistic"), "interpret the operating data and the strength of the evidence"),
    (("economic",), "connect demand, pricing, costs, and the wider economic environment"),
    (("financial statement", "financial reporting", "fsa"), "interpret the financial statements and operating ratios"),
    (("corporate", "issuer"), "evaluate the financing, governance, or capital-allocation decision"),
    (("equity",), "assess the business drivers and valuation implications"),
    (("fixed income", "bond"), "assess the borrowing, interest-rate, and credit implications"),
    (("derivative",), "consider how the business could manage market or input-cost risk"),
    (("alternative",), "evaluate the investment's cash flows, risks, and liquidity"),
    (("portfolio",), "connect the decision to risk, return, and portfolio objectives"),
)


def normalize_specialty(value: object) -> str:
    """Return a supported specialty key, falling back to standard context."""
    cleaned = str(value or "").strip().lower()
    from src.question_lenses import get_lenses
    return cleaned if cleaned in get_lenses() else DEFAULT_SPECIALTY


def specialty_label(value: object) -> str:
    from src.question_lenses import get_lenses
    return get_lenses()[normalize_specialty(value)]


def professional_context_cue(value: object, module: object = "") -> str:
    """Build a short, module-aware professional interpretation cue."""
    specialty = normalize_specialty(value)
    if specialty == DEFAULT_SPECIALTY:
        return ""

    module_text = str(module or "").strip().lower()
    action = "apply the CFA concept to the business decision"
    for keywords, candidate in _MODULE_ACTIONS:
        if any(keyword in module_text for keyword in keywords):
            action = candidate
            break

    if specialty not in _ROLE_CONTEXTS:
        return f"Question lens: {specialty_label(specialty)}."
    role = _ROLE_CONTEXTS[specialty]
    return f"Think like {role}: {action}."
