import pytest

from src.import_math_text import readable_math


@pytest.mark.parametrize("source, expected", [
    (r"(\\(34.2^\circ\text{C}\\))", "(34.2°C)"),
    (r"\\(pH\ 7.12\\)", "pH 7.12"),
    (r"\(\text{GABA}_\text{A}\)", "GABA_A"),
    (r"\(\dot{V}_E = 3\tau\)", "V\u0307_E = 3τ"),
    (r"$<32$ weeks, $3/6$, $KCNJ11$", "<32 weeks, 3/6, KCNJ11"),
    ("Costs $5 per item; $10 for two", "Costs $5 per item; $10 for two"),
    (r"A \$2,000,000 inventory write-down", "A $2,000,000 inventory write-down"),
    (r"Answer: \(\boxed{$221.1\text{ million}}\)", "Answer: $221.1 million"),
    (r"Costs \$5 and \$10", "Costs $5 and $10"),
    (r"A $4.2\text{ kg}$ infant", "A 4.2 kg infant"),
    (r"(\(122\text{ mEq/L}\))", "(122 mEq/L)"),
    (r"(\\(46, XX\\))", "(46, XX)"),
    (r"\(PaCO_2\), \(FiO_{2}\)", "PaCO₂, FiO₂"),
    (r"\(V_E = V_T \times f\)", "V_E = V_T × f"),
    (r"\[\Delta P = PIP - PEEP\]", "Δ P = PIP - PEEP"),
    (r"$$\frac{a+b}{\frac{c}{d}}$$", "(a+b)/((c)/(d))"),
    (r"\(10^{-3}\text{ cm}^{2}\)", "10⁻³ cm²"),
    (r"\(\mathrm{CO}_{2} \geq 50\text{ mmHg}\)", "CO₂ ≥ 50 mmHg"),
    ("Costs $5 and $10; mEq/L (46, XX).", "Costs $5 and $10; mEq/L (46, XX)."),
    (r"Unknown \(\overbrace{x}\) stays", r"Unknown \(\overbrace{x}\) stays"),
    (r"Broken \(\text{kg\)", r"Broken \(\text{kg\)"),
    (r"Path C:\text\file and x_y", r"Path C:\text\file and x_y"),
])
def test_readable_math_preserves_meaning(source, expected):
    assert readable_math(source) == expected
    assert readable_math(expected) == expected


@pytest.mark.parametrize("source, expected", [
    (r"**Question:** A \$2,000,000 write-down", "Question: A $2,000,000 write-down"),
    (r"An **increase** and *decrease*; __bold__ and _italic_.", "An increase and decrease; bold and italic."),
    (r"\(PaCO_2\) and x_y; 2 * 3 = 6; <5%", "PaCO₂ and x_y; 2 * 3 = 6; <5%"),
])
def test_readable_question_text(source, expected):
    from src.import_math_text import readable_question_text
    assert readable_question_text(source) == expected
    assert readable_question_text(expected) == expected


@pytest.mark.parametrize("source, expected", [
    (r"Answer: \(\boxed{$221.1\text{ million}}\)", r"Answer: $\boxed{\$221.1\text{ million}}$"),
    (r"\\(x \times 2\\)", r"$x \times 2$"),
    (r"\[\frac{a}{b}\]", "\n\n$$\n" + r"\frac{a}{b}" + "\n$$\n\n"),
    (r"$$\boxed{\$221.06\text{ million}}$$", r"$$\boxed{\$221.06\text{ million}}$$"),
    (r"Costs $5 and $10. **Keep bold.**", r"Costs $5 and $10. **Keep bold.**"),
])
def test_math_markdown(source, expected):
    from src.import_math_text import math_markdown
    assert math_markdown(source) == expected
    assert math_markdown(expected) == expected
