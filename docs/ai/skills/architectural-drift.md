# Skill: Architectural Drift Detection

Goal:
Detect gradual architecture degradation.

Check:
- duplicated logic
- hidden coupling
- boundary violations
- unnecessary abstractions
- AI leakage into deterministic core

Warn when:
- similar logic appears in multiple places
- responsibilities become unclear
- orchestration and computation mix together

Output:
- detected drift
- risk level
- minimal correction strategy