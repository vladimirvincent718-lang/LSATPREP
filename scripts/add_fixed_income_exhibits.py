"""Add distractor-rich fixed-income exhibit questions to the live question bank.

The migration is idempotent: ``import_questions`` skips matching content hashes.
It also takes a timestamped database backup before the first insertion.
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.database import DB_PATH, _make_content_hash, get_connection, insert_questions


SOURCE = "StudyForge custom fixed-income exhibits 2026-08-21"
TAGS = "cfa-level-1, fixed-income, exhibit-table, distractor-rich, custom"


def _question(
    *,
    module: str,
    difficulty: int,
    passage: str,
    stimulus: str,
    choices: tuple[str, str, str],
    answer: str,
    explanation: str,
    wrong: tuple[str, str, str],
) -> dict:
    return {
        "section_type": module,
        "question_type": "Exhibit-Based Multiple Choice",
        "difficulty": difficulty,
        "passage": passage.strip(),
        "stimulus": stimulus,
        "choice_a": choices[0],
        "choice_b": choices[1],
        "choice_c": choices[2],
        "choice_d": "",
        "choice_e": "",
        "correct_answer": answer,
        "explanation": explanation,
        "wrong_answer_a": "" if answer == "A" else wrong[0],
        "wrong_answer_b": "" if answer == "B" else wrong[1],
        "wrong_answer_c": "" if answer == "C" else wrong[2],
        "wrong_answer_d": "",
        "wrong_answer_e": "",
        "source": SOURCE,
        "tags": TAGS,
    }


QUESTION_CANDIDATES = [
    _question(
        module="Learning Module 6: Fixed-Income Bond Valuation: Prices and Yields",
        difficulty=3,
        passage="""
**Bond A — market data (annual-pay)**

| Item | Value |
|---|---:|
| Par value | $1,000 |
| Coupon rate | 5.00% |
| Years to maturity | 3 |
| Yield to maturity | 4.00% |
| Issuer rating | A− |
| Benchmark spread | 92 bps |
| Issue price | $998.50 |
| Next call date | None |
""",
        stimulus="Using the exhibit, the value of Bond A per $1,000 of par is closest to:",
        choices=("$1,027.75", "$972.25", "$1,000.00"),
        answer="A",
        explanation=(
            "Discount only the contractual cash flows at the YTM: "
            "$50/1.04 + $50/1.04^2 + $1,050/1.04^3 = $1,027.75. "
            "The rating, benchmark spread, issue price, and nonexistent call date are decoys."
        ),
        wrong=("", "This reverses the premium relationship; the coupon exceeds the YTM.",
               "Par would be appropriate if the coupon rate equaled the YTM."),
    ),
    _question(
        module="Learning Module 8: Yield and Yield Spread Measures for Floating-Rate Instruments",
        difficulty=3,
        passage="""
**Quarterly-reset floating-rate note**

| Item | Value |
|---|---:|
| Principal | $5,000,000 |
| 3-month reference rate at reset | 3.10% |
| Quoted margin | 140 bps |
| Discount margin | 165 bps |
| Coupon floor | 1.50% |
| Coupon cap | 5.00% |
| Days since prior reset | 18 |
| Current clean price | 99.35 |
""",
        stimulus="Assuming four equal coupon periods per year, the next quarterly coupon payment is closest to:",
        choices=("$56,250", "$59,375", "$225,000"),
        answer="A",
        explanation=(
            "The annualized coupon rate is 3.10% + 1.40% = 4.50%, within the cap and floor. "
            "$5,000,000 × 4.50% / 4 = $56,250. The discount margin, price, and days since reset do not set the coupon."
        ),
        wrong=("", "This incorrectly uses the 165 bp discount margin instead of the quoted margin.",
               "This is the annual coupon amount and does not divide by four."),
    ),
    _question(
        module="Learning Module 14: Credit Risk",
        difficulty=3,
        passage="""
**One-year credit risk estimate**

| Measure | Estimate |
|---|---:|
| Exposure at default (EAD) | $8,000,000 |
| Probability of default (PD) | 2.50% |
| Loss given default (LGD) | 40.00% |
| Recovery rate | 60.00% |
| Bond spread | 185 bps |
| Modified duration | 4.2 |
| Current market value | $7,840,000 |
""",
        stimulus="Based on the exhibit, the one-year expected credit loss is closest to:",
        choices=("$80,000", "$120,000", "$200,000"),
        answer="A",
        explanation=(
            "Expected loss = PD × LGD × EAD = 2.50% × 40% × $8,000,000 = $80,000. "
            "Recovery is already captured by LGD; spread, duration, and market value are not inputs."
        ),
        wrong=("", "This applies the 60% recovery rate as though it were LGD.",
               "This calculates expected exposure at default before applying LGD."),
    ),
    _question(
        module="Learning Module 10: Interest Rate Risk and Return",
        difficulty=3,
        passage="""
**Six-month holding-period record (per $100 par)**

| Item | Beginning | Ending |
|---|---:|---:|
| Clean price | $98.40 | $99.10 |
| Accrued interest | $0.00 | $0.00 |
| Yield to maturity | 5.30% | 5.05% |
| Benchmark yield | 4.10% | 3.95% |
| Credit spread | 120 bps | 110 bps |
| Coupon received during period |  | $2.50 |
""",
        stimulus="The bond's six-month holding-period return is closest to:",
        choices=("0.71%", "3.25%", "5.05%"),
        answer="B",
        explanation=(
            "Because accrued interest is zero at both endpoints, return = ($99.10 − $98.40 + $2.50) / $98.40 = 3.25%. "
            "The yield and spread changes help explain the price move but are not separate cash returns."
        ),
        wrong=("This includes only the price change and omits the coupon.", "", "This confuses ending YTM with realized holding-period return."),
    ),
    _question(
        module="Learning Module 9: The Term Structure of Interest Rates: Spot, Par, and Forward Curves",
        difficulty=4,
        passage="""
**Annual-compounding government curve**

| Maturity | Spot rate | Par rate | Zero price per $100 |
|---:|---:|---:|---:|
| 1 year | 2.60% | 2.60% | 97.466 |
| 2 years | 3.20% | 3.19% | 93.894 |
| 3 years | 4.00% | 3.96% | 88.900 |
| 5 years | 4.55% | 4.43% | 80.041 |
""",
        stimulus="The one-year forward rate beginning two years from today is closest to:",
        choices=("4.80%", "5.62%", "6.45%"),
        answer="B",
        explanation=(
            "Use only the 2- and 3-year spot rates: (1 + f2,3) = 1.04^3 / 1.032^2, so f2,3 = 5.62%. "
            "The par rates, zero prices, and 1- and 5-year rows are decoys."
        ),
        wrong=("This uses an unsupported shortcut based on the difference in spot rates.", "",
               "This overstates the forward rate by compounding the spot-rate difference incorrectly."),
    ),
    _question(
        module="Learning Module 11: Yield-Based Bond Duration Measures and Properties",
        difficulty=4,
        passage="""
**Bond risk report**

| Measure | Value |
|---|---:|
| Macaulay duration | 6.42 |
| Yield to maturity | 5.40% |
| Coupon frequency | Semiannual |
| Effective duration | 6.08 |
| Convexity | 54.7 |
| Current price | 96.80 |
| Coupon rate | 4.75% |
""",
        stimulus="The bond's modified duration is closest to:",
        choices=("6.08", "6.25", "6.42"),
        answer="B",
        explanation=(
            "Modified duration = Macaulay duration / (1 + YTM/m) = 6.42 / (1 + 0.054/2) = 6.25. "
            "Effective duration, convexity, price, and coupon rate are not needed."
        ),
        wrong=("This selects the separately reported effective duration.", "", "This leaves Macaulay duration unadjusted for yield."),
    ),
    _question(
        module="Learning Module 16: Credit Analysis for Corporate Issuers",
        difficulty=4,
        passage="""
**Selected corporate data ($ millions)**

| Item | Amount |
|---|---:|
| Revenue | 620 |
| Cost of goods sold | 390 |
| Operating income (EBIT) | 72 |
| Depreciation and amortization | 18 |
| Interest expense | 24 |
| Capital expenditures | 31 |
| Total debt | 450 |
| Cash and equivalents | 60 |
| Accounts receivable | 74 |
""",
        stimulus="The issuer's net debt-to-EBITDA ratio is closest to:",
        choices=("4.33×", "5.00×", "5.42×"),
        answer="A",
        explanation=(
            "EBITDA = EBIT + D&A = $72 + $18 = $90 million. Net debt = $450 − $60 = $390 million. "
            "Net debt/EBITDA = $390/$90 = 4.33×. Revenue, COGS, interest, capex, and receivables are decoys."
        ),
        wrong=("", "This uses gross debt rather than net debt.", "This incorrectly adds cash to debt."),
    ),
    _question(
        module="Learning Module 19: Mortgage-Backed Security (MBS) Instrument and Market Features",
        difficulty=4,
        passage="""
**Mortgage pass-through comparison**

| Security | WAC | Price | Weighted avg. loan age | Avg. LTV | Servicing fee |
|---|---:|---:|---:|---:|---:|
| A | 3.10% | 96.4 | 14 months | 68% | 25 bps |
| B | 6.25% | 108.7 | 26 months | 71% | 25 bps |
| C | 4.20% | 100.1 | 8 months | 82% | 25 bps |

Current mortgage rates are approximately **3.75%**.
""",
        stimulus="Based on the exhibit, which security is most exposed to contraction risk if mortgage rates remain near their current level?",
        choices=("Security A", "Security B", "Security C"),
        answer="B",
        explanation=(
            "Security B's 6.25% WAC is far above current mortgage rates, giving borrowers the strongest refinancing incentive. "
            "Its premium price also makes accelerated return of principal especially harmful. LTV, loan age, and the common servicing fee are secondary decoys here."
        ),
        wrong=("Its WAC is below current mortgage rates, so refinancing incentive is weak.", "",
               "Its WAC is only modestly above current rates and its price is near par."),
    ),
    _question(
        module="Learning Module 12: Yield-Based Bond Convexity and Portfolio Properties",
        difficulty=5,
        passage="""
**Option-free bond analytics**

| Measure | Value |
|---|---:|
| Modified duration | 7.80 |
| Macaulay duration | 8.01 |
| Convexity | 68.0 |
| Yield change | +75 bps |
| Coupon rate | 5.25% |
| Credit spread | 135 bps |
| Current price | 102.40 |
""",
        stimulus="Using duration and convexity, the estimated percentage price change is closest to:",
        choices=("−6.04%", "−5.85%", "−5.66%"),
        answer="C",
        explanation=(
            "Estimate ΔP/P = −ModDur(Δy) + 0.5 × Convexity × (Δy)^2. "
            "That is −7.80(0.0075) + 0.5(68)(0.0075^2) = −5.66%. Macaulay duration, coupon, spread, and price are decoys."
        ),
        wrong=("This applies the convexity adjustment with the wrong sign.",
               "This is the duration-only estimate and omits positive convexity.", ""),
    ),
    _question(
        module="Learning Module 13: Curve-Based and Empirical Fixed-Income Risk Measures",
        difficulty=5,
        passage="""
**Portfolio key-rate report**

| Curve point | Key-rate duration | Forecast yield shift |
|---:|---:|---:|
| 2-year | 0.60 | +10 bps |
| 5-year | 2.10 | −5 bps |
| 10-year | 4.40 | +20 bps |

| Other portfolio measure | Value |
|---|---:|
| Effective duration | 7.10 |
| Convexity | 61.0 |
| Yield to maturity | 4.85% |
| Average coupon | 4.30% |
""",
        stimulus="Using the key-rate durations and ignoring convexity, the portfolio's estimated percentage price change is closest to:",
        choices=("−0.84%", "−0.75%", "+0.84%"),
        answer="A",
        explanation=(
            "ΔP/P ≈ −Σ(KRD × Δy) = −[0.60(0.0010) + 2.10(−0.0005) + 4.40(0.0020)] = −0.835%, or −0.84%. "
            "Effective duration cannot represent this nonparallel shift; convexity, YTM, and coupon are decoys."
        ),
        wrong=("", "This treats the 5-year rate decline as a price loss instead of a gain.",
               "This reverses the sign of the rate-price relationship."),
    ),
    _question(
        module="Learning Module 7: Yield and Yield Spread Measures for Fixed-Rate Bonds",
        difficulty=5,
        passage="""
**Callable bond quotations**

| Item | Value |
|---|---:|
| Clean price | 104.20 |
| Accrued interest | 1.10 |
| Yield to maturity | 4.60% |
| Yield to first call | 3.85% |
| Yield to second call | 4.05% |
| Yield to put | 5.10% |
| Coupon rate | 5.75% |
| Option-adjusted spread | 118 bps |
""",
        stimulus="Assuming the issuer may call the bond on either call date and the investor does not control the call, the bond's yield-to-worst is closest to:",
        choices=("3.85%", "4.05%", "4.60%"),
        answer="A",
        explanation=(
            "Yield-to-worst is the lowest yield among the issuer-controlled maturity and call outcomes: min(4.60%, 3.85%, 4.05%) = 3.85%. "
            "The investor-controlled put yield, price, accrued interest, coupon, and OAS do not determine YTW."
        ),
        wrong=("", "This is the second-call yield, but the first call produces a lower return.",
               "This ignores both issuer call outcomes."),
    ),
    _question(
        module="Learning Module 17: Fixed-Income Securitization",
        difficulty=5,
        passage="""
**Sequential loss waterfall ($ millions)**

| Tranche | Opening principal | Coupon | Rating |
|---|---:|---:|---:|
| Senior | 84 | 4.2% | AAA |
| Mezzanine | 10 | 6.8% | BBB |
| Equity | 6 | Residual | Unrated |

| Collateral information | Value |
|---|---:|
| Opening collateral balance | $100 million |
| Defaulted principal | $12 million |
| Recovery rate on defaults | 25% |
| Excess spread available | $0 |
| Scheduled principal collections | $4 million |

Credit losses are allocated first to equity, then mezzanine, then senior.
""",
        stimulus="After allocating the collateral credit loss, the mezzanine tranche's principal loss as a percentage of its opening balance is closest to:",
        choices=("25%", "30%", "60%"),
        answer="B",
        explanation=(
            "Collateral loss = $12m × (1 − 25%) = $9m. Equity absorbs $6m, leaving $3m for mezzanine. "
            "$3m/$10m = 30%. Coupons, ratings, scheduled principal, and the original collateral balance are decoys for loss allocation."
        ),
        wrong=("This mistakes the recovery rate for the mezzanine loss percentage.", "",
               "This applies the exhausted equity balance as though it were the mezzanine loss."),
    ),
]


PILOT_MODULE = (
    "Learning Module 19: Mortgage-Backed Security (MBS) Instrument and Market Features"
)

QUESTIONS = [
    _question(
        module=PILOT_MODULE,
        difficulty=3,
        passage="""
**Monthly mortgage pass-through report**

| Item | Value |
|---|---:|
| Beginning pool balance | $10,000,000 |
| Weighted-average mortgage rate | 6.00% |
| Servicing and guarantee fee | 25 bps |
| Scheduled principal | $20,000 |
| Prepayments | $180,000 |
| Weighted-average loan age | 31 months |
| Weighted-average LTV | 72% |
| Current 30-year mortgage rate | 4.25% |
""",
        stimulus="Ignoring day-count differences, the total cash flow passed through to investors this month is closest to:",
        choices=("$247,917", "$227,917", "$250,000"),
        answer="A",
        explanation=(
            "The investor pass-through rate is 6.00% - 0.25% = 5.75%. Monthly interest is "
            "$10,000,000 x 5.75% / 12 = $47,917. Add $20,000 scheduled principal and "
            "$180,000 prepayments for total cash flow of $247,917. Loan age, LTV, and the current mortgage rate are decoys."
        ),
        wrong=(
            "",
            "This adds principal to interest calculated after incorrectly deducting an extra 25 bps.",
            "This uses gross mortgage interest and omits the servicing and guarantee fee.",
        ),
    ),
    next(
        question
        for question in QUESTION_CANDIDATES
        if question["section_type"] == PILOT_MODULE and question["difficulty"] == 4
    ),
    _question(
        module=PILOT_MODULE,
        difficulty=5,
        passage="""
**PAC/support CMO principal allocation ($ millions)**

| Item | Value |
|---|---:|
| PAC tranche scheduled principal this month | $1.00 |
| PAC collar: lower-band collateral principal | $0.80 |
| PAC collar: upper-band collateral principal | $1.20 |
| Actual collateral principal received | $1.45 |
| Support tranche principal before payment | $0.60 |
| PAC tranche principal before payment | $18.00 |
| Current prepayment speed | 225 PSA |
| Collateral weighted-average coupon | 5.80% |

The support tranche absorbs deviations from the PAC schedule while it has sufficient principal outstanding.
""",
        stimulus="The principal payment allocated to the PAC tranche this month is closest to:",
        choices=("$0.85 million", "$1.45 million", "$1.00 million"),
        answer="C",
        explanation=(
            "The PAC receives its $1.00 million scheduled principal. Actual collateral principal exceeds the schedule by "
            "$0.45 million, which is less than the support tranche's $0.60 million outstanding balance, so support can "
            "absorb the full deviation. The collar endpoints, PSA speed, coupon, and PAC balance are decoys for this allocation."
        ),
        wrong=(
            "This subtracts the support balance from actual principal rather than applying the PAC schedule.",
            "This sends all collateral principal to the PAC tranche and ignores support protection.",
            "",
        ),
    ),
]


def _new_question_count() -> int:
    conn = get_connection()
    try:
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT content_hash FROM questions WHERE course_id = 15"
            ).fetchall()
        }
    finally:
        conn.close()
    hashes = {
        _make_content_hash(
            q["stimulus"], q["choice_a"], q["choice_b"], q["choice_c"],
            q["choice_d"], q["choice_e"], q["correct_answer"]
        )
        for q in QUESTIONS
    }
    return len(hashes - existing)


def _scope_changes() -> tuple[list[int], list[int]]:
    desired_hashes = {
        _make_content_hash(
            q["stimulus"], q["choice_a"], q["choice_b"], q["choice_c"],
            q["choice_d"], q["choice_e"], q["correct_answer"]
        )
        for q in QUESTIONS
    }
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT id, content_hash, COALESCE(is_archived, 0) AS is_archived
               FROM questions WHERE course_id = 15 AND source = ?""",
            (SOURCE,),
        ).fetchall()
    finally:
        conn.close()
    archive_ids = [
        int(row["id"])
        for row in rows
        if row["content_hash"] not in desired_hashes and not row["is_archived"]
    ]
    restore_ids = [
        int(row["id"])
        for row in rows
        if row["content_hash"] in desired_hashes and row["is_archived"]
    ]
    return archive_ids, restore_ids


def main() -> None:
    pending = _new_question_count()
    archive_ids, restore_ids = _scope_changes()
    if pending or archive_ids or restore_ids:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = DB_PATH.with_name(f"lsat_app_before_mbs_exhibit_pilot_{stamp}.db")
        shutil.copy2(DB_PATH, backup)
        print(f"Backup: {backup}")
    if archive_ids or restore_ids:
        conn = get_connection()
        try:
            if archive_ids:
                placeholders = ",".join("?" for _ in archive_ids)
                conn.execute(
                    f"""UPDATE questions
                        SET is_archived = 1,
                            archived_at = CURRENT_TIMESTAMP,
                            archive_reason = 'Pilot narrowed to MBS exhibits only'
                        WHERE id IN ({placeholders})""",
                    archive_ids,
                )
            if restore_ids:
                placeholders = ",".join("?" for _ in restore_ids)
                conn.execute(
                    f"""UPDATE questions
                        SET is_archived = 0, archived_at = NULL, archive_reason = ''
                        WHERE id IN ({placeholders})""",
                    restore_ids,
                )
            conn.commit()
        finally:
            conn.close()
    inserted, skipped_id, skipped_content = insert_questions(QUESTIONS, course_id=15)
    print(
        f"Inserted: {inserted}; archived outside pilot: {len(archive_ids)}; "
        f"restored inside pilot: {len(restore_ids)}; skipped ID: {skipped_id}; "
        f"skipped duplicate content: {skipped_content}"
    )


if __name__ == "__main__":
    main()
