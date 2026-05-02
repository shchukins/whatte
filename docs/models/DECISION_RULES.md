# Decision Rules

## 1. Purpose

This document defines the deterministic mapping from `readiness_score` to a training recommendation.

Input:

- `readiness_score` in range `0..100`
- optional `fallback_mode`
- optional explanation inputs from load and recovery layers

Output:

- recommendation zone
- reason string
- optional briefing text in downstream response

This layer consumes readiness. It does not recompute load, recovery, freshness, HRV, sleep, or readiness.

---

## 2. Principles

Decision rules must be:

- rule-based
- deterministic
- explainable
- reproducible

Decision rules must not use:

- ML
- LLM-generated recommendations
- hidden probabilistic behavior
- implicit changes to physiology or metric definitions

---

## 3. Recommendation mapping

Boundary rule:

- exact boundary values use the higher readiness zone, except `75`
- `75` remains `moderate`
- `high_intensity` starts only when `readiness_score > 75`

| Readiness score | Zone | Recommendation |
| --- | --- | --- |
| `< 40` | `recovery` | Recovery or rest |
| `40 <= score < 60` | `endurance` | Easy endurance |
| `60 <= score <= 75` | `moderate` | Moderate aerobic or controlled tempo |
| `> 75` | `high_intensity` | High intensity if planned |

---

## 4. Zones

### 4.1 Recovery

Meaning:

- readiness is low
- current state suggests limited ability to absorb additional load

Physiological interpretation:

- fatigue is high, recovery is low, or both
- the priority is restoring autonomic and muscular readiness

Recommended training type:

- rest
- mobility
- very easy spin or walk
- no intervals
- no hard strength work

### 4.2 Endurance

Meaning:

- readiness is acceptable but not strong
- training is possible, but intensity should stay constrained

Physiological interpretation:

- the athlete can likely tolerate low-intensity aerobic work
- freshness or recovery is not strong enough to justify intensity

Recommended training type:

- easy endurance
- Zone 1 / Zone 2
- short aerobic ride or run
- technique work
- avoid hard intervals

### 4.3 Moderate

Meaning:

- readiness is solid
- the athlete can usually handle meaningful aerobic work

Physiological interpretation:

- load and recovery are balanced enough for productive training
- fatigue is not dominant, but the system is not signaling a peak day

Recommended training type:

- moderate aerobic session
- controlled tempo
- endurance with limited intensity
- strength or skills if already planned

### 4.4 High intensity

Meaning:

- readiness is high
- the athlete appears prepared for demanding work

Physiological interpretation:

- freshness and recovery are favorable
- the current state can support higher training stress

Recommended training type:

- intervals
- threshold / VO2 work
- race-specific intensity
- hard strength work if compatible with the plan

High intensity is allowed only if it fits the training plan. Readiness permits intensity; it does not require it.

---

## 5. Explanation rules

The current reason string is assembled from deterministic components in `backend.services.decision_engine.build_recommendation`.

```text
Readiness score is <score>/100. <available inputs>. <fallback note>. Recommendation is <recommendation>.
```

Current components:

- readiness score
- freshness, when `freshness_norm` is available
- recovery, when `recovery_score_simple` is available
- fallback note for `recovery_only` or `load_only`
- final recommendation label

Example JSON:

```json
{
  "recommendation": "endurance",
  "reason": "Readiness score is 55.7/100. Freshness is available at 54/100. Recovery is available at 58.2/100. Recommendation is endurance."
}
```

Explainability requirement:

- every recommendation must be traceable to `readiness_score`
- available load/recovery inputs should be visible in `reason`
- fallback modes must be explicit
- no ML or LLM-generated text is used

---

## 6. Edge cases

### 6.1 `fallback_mode = recovery_only`

Meaning:

- recommendation is based only on `recovery_score_simple`
- load/freshness context is unavailable

Decision behavior:

- use the same readiness-to-zone mapping
- reason string must state that load context is missing
- keep the recommendation tied to the computed readiness score

Current wording:

```text
Load context is missing, so the recommendation is conservative.
```

### 6.2 `fallback_mode = load_only`

Meaning:

- recommendation is based only on `freshness_norm`
- recovery context is unavailable

Decision behavior:

- use the same readiness-to-zone mapping
- reason string must state that recovery context is missing
- avoid HRV/sleep-based claims

Current wording:

```text
Recovery context is missing, so freshness should not be over-interpreted.
```

### 6.3 Missing HRV or sleep

Meaning:

- recovery may be partial or less reliable
- the exact impact is defined by the recovery layer, not by decision rules

Decision behavior:

- do not invent missing HRV or sleep interpretation
- use only the `recovery_score_simple` already produced by recovery layer
- mention fallback only when the readiness explanation has `fallback_mode`

---

## 7. Constraints

This document defines product decision rules only.

It does not:

- change readiness formula
- change freshness or recovery definitions
- introduce new model inputs
- create a production training plan
- replace coach judgment

The decision layer remains deterministic decision support on top of `readiness_score`.
