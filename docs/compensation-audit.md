# Compensation implementation audit

Reviewed 2026-09-10 against the vendored FlowKit 1.3.2 code, installed FlowUtils
1.2.2, Cytoflow source and official package documentation. This is a code and
synthetic-fixture audit, not validation against lab controls or a reference export.

## Matrix application: correct convention

Agentflow uses `measured = true @ spillover`: rows are source detectors, columns
are receiving detectors, coefficients are fractions and the diagonal is one.
FlowKit maps matrix labels to acquired detector indices and delegates correction
to FlowUtils. This agrees with the documented labelled-channel interface in
[FlowUtils](https://flowutils.readthedocs.io/en/latest/compensate.html) and
[FlowKit](https://flowkit.readthedocs.io/en/latest/matrix.html).

Independent asymmetric three-channel fixtures exercise both explicit matrices
and FCS SPILLOVER metadata with shuffled labels and interleaved scatter data.
They recover known signals, preserve negative values and scatter, retain raw
events, and give the expected gate membership after transformation. Reapplying
the same recipe does not compensate twice; switching to uncompensated mode
restores the acquired signal space.

Singular and severely ill-conditioned matrices fail rather than using a
pseudoinverse. The condition-number cutoff is a numerical guard, not a guarantee
of good controls. Percentage matrices with a 100 diagonal fail; values above one
off-diagonal are allowed. A unit diagonal alone cannot identify every incorrectly
labelled/transposed matrix or inverse: users must supply the documented convention.

## Estimation: conventional median differences, not Cytoflow's regression

Our estimator divides the positive-minus-negative median change in each receiving
detector by the change in the stained detector. It uses two explicitly selected
populations within each single-stain tube and no display transformation.


In contrast, the inspected
[Cytoflow implementation](https://github.com/cytoflow/cytoflow/blob/c31a6f5dfcecb471aad6386c97c30ac6dc39c5e8/cytoflow/operations/bleedthrough_linear.py)
fits through-origin slopes after prior operations, selected cleanup and endpoint
clipping, then applies a pseudoinverse. Its
[workflow guide](https://cytoflow.readthedocs.io/en/stable/user_manual/howto/bleedthrough.html)
includes background subtraction and control acquisition requirements. Agentflow
does not claim numerical equivalence to that workflow and copies no Cytoflow code.

The seeded four-channel fixtures recover the known spillover matrix within
absolute tolerance 0.0002. This covers clean synthetic controls, not heterogeneous
autofluorescence, tandem-dye variation or instrument drift.

## Defects reproduced and corrected

1. **Gain-scaled saturation was missed.** FlowKit's raw events are already
   acquisition-preprocessed; comparing them directly to unscaled PnR values could
   miss saturation. Limits now use the same gain/amplification units as the data.
   The shared acquisition-quality flags use the correction too.
2. **Receiving-channel saturation was missed.** Checks now include every matrix
   detector in both selected positive and negative populations. Saturated controls
   fail; events are not silently removed to force an estimate.
3. **Diagnostic cleanup differed from estimation.** The GUI histogram already
   honored cleanup, but exported plots showed the full control. New estimates
   embed the cleanup recipe and gate. Diagnostics use that exact selection and
   native FlowKit compensation, even if the source cleanup file later changes.
   Legacy estimates with only a cleanup hash must be re-estimated for this review.
4. **Acquisition mismatch checks were missing.** New estimates record instrument,
   detector gain, range, amplification and reported voltage. Contradictory settings
   across controls or when applying the matrix to a sample fail. The comparison
   is label-based. Missing reference metadata stays unknown; old/imported matrices
   without acquisition provenance cannot receive this comparison.

`tests/test_compensation_audit.py` covers these cases, plus control/sample voltage
mismatches and exact cleanup-event selection in diagnostics. Existing desktop
tests cover explicit matrix application and invalidation of gate review state.

## Remaining work before a validated lab workflow

- Validate real positive/negative controls and compensated distributions against
  an approved reference analysis. Matching metadata cannot establish biological
  suitability or detect unreported instrument changes.
- Support a separate matched unstained-negative file when a single-stain tube
  does not contain both populations. Currently both must be in the same tube.
- Add quantitative residual, brightness/separation and uncertainty diagnostics;
  current plots require human review and do not certify a matrix.
- Regression/AutoSpill, automatic autofluorescence subtraction and spectral
  unmixing are not implemented in Agentflow's compensation workflow.
- Arbitrary vendor matrix dialects and already hardware-compensated exports need
  explicit interpretation. The software cannot infer the correct history from
  missing metadata.

## Practical conclusion

The application path is consistent with FlowKit/FlowUtils and the estimator is a
reasonable traditional starting point for conventional few-channel experiments.
Use reviewed single-stain controls or a reviewed imported matrix. Do not interpret
synthetic test success, a clean heatmap or a saved YAML file as biological validation.
