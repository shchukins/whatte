# Calibration evaluation contract for #77

## Decision boundary

The first phase provides one decision-to-outcome record per canonical activity.
The second phase adds read-only descriptive comparisons. A recommendation is a
permitted training category, not a prediction of RPE or next-day recovery. The
current `good_day_probability` is a score mapping, not a calibrated probability.
Neither a high RPE nor poor next-day recovery alone is a model error.

## Comparison units and windows

- Activity-level RPE comparisons use one canonical activity and its effective
  1-10 RPE when present. Historical 1-5 RPE is a separate series. Never
  convert between scales or combine their score distributions.
- Next-day recovery comparisons use one local training day, with the latest
  eligible decision before the first activity and one recovery observation on
  the next local day. Multiple activities on the training day share that
  outcome; report the activity count, total included TSS, and whether all,
  some, or none of the activities have measured load as context.
- The CLI's inclusive local activity-date range is the comparison window.
  The requested end date may read recovery on the following local date.

## Outputs and limits

- Report explicit counts for all activities/days and for each missing or
  incompatible decision, load, RPE, and recovery state. A comparison is not
  eligible when its required evidence is unavailable.
- Report RPE and recovery distributions by decision recommendation, sport,
  load inclusion, and RPE scale. These are descriptive counts, not model error
  rates or calibrated probabilities.
- Mark review cases only when the observed session intensity and subjective
  cost point in different directions using existing versioned intensity bands
  and 1-10 RPE labels. Cases are hypotheses for inspection, never automatic
  verdicts about readiness or recommendation correctness.
- Keep actual model-error scores and over/underestimation verdicts unavailable
  until #95 defines a defensible outcome target and comparison baseline.

This is an offline, read-only evaluation contract. It does not update readiness,
change thresholds, add snapshot events, or create a general export pipeline.
