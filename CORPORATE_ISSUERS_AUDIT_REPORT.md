# Corporate Issuers Question Bank Audit

**Audit date:** June 12, 2026  
**Course:** CFA Level I Corporate Issuers  
**Database reviewed:** `data/lsat_app.db`

## Executive Summary

The entire Corporate Issuers bank was reviewed for answer-key validity, calculation
consistency, self-contained wording, answer-choice integrity, explanation consistency,
and reported-question issues.

- Questions reviewed: **401**
- Questions remaining active after cleanup: **173**
- Questions archived after cleanup: **228**
- User-submitted Corporate Issuers reports resolved: **9**
- Active V2 transformed questions: **0**
- Active questions requiring a missing prior question: **0**
- Active questions with invalid or blank answer keys: **0**

The largest problem was the 175-question V2 transformed batch. Its transformed numbers,
answer choices, answer keys, and explanations were not reliably synchronized. All 175 V2
questions are now inactive. Questions that depended on missing prior-question context or
contained truncated/underspecified wording were also retired.

## Reported Questions

| Database ID | Question ID | Result |
|---:|---|---|
| 1008 | CC-0002 | Corrected and restored. Answer: **Limited partnership**. |
| 1010 | CC-0004 | Corrected and restored. Answer: distributed corporate earnings may face **double taxation**. |
| 1015 | CC-0009 | Kept archived. The prompt was ambiguous because multiple structures can be pass-through entities. |
| 1017 | CC-0011 | Corrected and restored. `$100 million x 21% = $21 million`. |
| 1019 | CC-0013 | Kept archived. It required an absent prior question. |
| 4459 | CC-0230 | Kept archived with the unreliable V2 batch. The key was correct, but the explanation metadata was wrong. |
| 4460 | CC-0231 | Kept archived with the unreliable V2 batch. `87% x $38 billion = $33.06 billion`, which was absent from the choices. |
| 4461 | CC-0232 | Kept archived with the unreliable V2 batch. `$115 million - $24.2 million = $90.8 million`, which was absent from the choices. |

Report IDs 29 and 30 were duplicate reports for database question 4461; both were resolved.

## Additional Corrections

- **Database ID 1229 / CC-0223:** Corrected the ROIC-implied equity value from
  `47035` to `47024`, added explicit rounding language, and replaced the generic
  explanation with the full calculation.
- Retired **45** questions that depended on unavailable prior-question context.
- Retired **6** truncated, underspecified, or materially mislabeled questions.
- Retired the full **175-question V2 transformed batch** because answer metadata and
  transformed calculations were unreliable.

## Final Active Questions by Module

| Module | Active |
|---|---:|
| Alpha Street CFA Level 1 | 1 |
| Organizational Forms, Corporate Issuer Features, and Ownership | 40 |
| Investors and Other Stakeholders | 25 |
| Corporate Governance | 42 |
| Working Capital and Liquidity | 35 |
| Capital Investments and Capital Allocation | 30 |
| **Total** | **173** |

## Verification

The retained bank received an answer-by-answer calculation and concept pass. Automated
quality checks now enforce valid keys, unique choices, self-contained prompts, removal of
the V2 batch, and the reported-question repairs.

Authoritative references used for the reported concepts and curriculum scope:

- IRS, **Forming a corporation**: corporate profit is taxed when earned and may be taxed
  again when distributed as dividends.
  <https://www.irs.gov/businesses/small-businesses-self-employed/forming-a-corporation>
- U.S. Small Business Administration, **Choose a business structure**: a limited
  partnership has a general partner with unlimited liability and limited partners with
  limited liability.
  <https://www.sba.gov/business-guide/launch-your-business/choose-business-structure>
- IRS, **Partnerships**: partnership income and losses generally pass through to partners.
  <https://www.irs.gov/businesses/partnerships>
- IRS, **S corporation stock and debt basis**: S corporation items generally flow through
  to shareholders, illustrating why the original broad pass-through question was ambiguous.
  <https://www.irs.gov/businesses/small-businesses-self-employed/s-corporation-stock-and-debt-basis>
- CFA Institute, **2025 Level I Corporate Issuers learning outcomes**: confirms the
  reviewed scope for organizational forms, stakeholders, governance, working capital,
  liquidity, NPV, IRR, ROIC, and real options.
  <https://www.cfainstitute.org/sites/default/files/-/media/documents/study-session/2025-l1-los-t3.pdf>
- CFA Institute, **Capital Investments and Capital Allocation**: confirms NPV, IRR, ROIC,
  real-option, and capital-allocation concepts.
  <https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/capital-investments-and-capital-allocation>

## Validation Results

- Full automated test suite: **10 passed**
- SQLite integrity check: **ok**
- SQLite foreign-key check: **no violations**
- Active questions referencing missing prior questions: **0**
- Active V2 transformed questions: **0**
- Unresolved Corporate Issuers issue reports: **0**

## Recovery

A pre-cleanup database backup was created at:

`C:\Users\Esther\AppData\Local\Temp\lsat_app_before_corporate_issuers_cleanup_20260612_034430.db`

An additional checkpoint after the first cleanup pass was created at:

`C:\Users\Esther\AppData\Local\Temp\lsat_app_before_corporate_issuers_cleanup_20260612_034609.db`
