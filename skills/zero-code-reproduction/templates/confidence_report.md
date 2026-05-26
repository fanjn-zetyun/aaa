# Reproduction Scaffold — Confidence Report

**Paper**: {{ paper_title }}
**Generated**: {{ date }}
**Generator**: Hermes Agent / zero-code-reproduction skill v1.0
**Domain**: {{ domain }} | **Experiment Type**: {{ experiment_type }}

---

## Overall Reproduction Readiness

| Aspect | Status | Confidence |
|--------|--------|------------|
| Paper Understanding | {{ understanding_status }} | {{ understanding_confidence }} |
| Architecture/Method Extraction | {{ architecture_status }} | {{ architecture_confidence }} |
| Hyperparameter Extraction | {{ hyperparam_status }} | {{ hyperparam_confidence }} |
| Data Pipeline | {{ data_status }} | {{ data_confidence }} |
| Training/Execution Pipeline | {{ training_status }} | {{ training_confidence }} |
| Evaluation Pipeline | {{ eval_status }} | {{ eval_confidence }} |

**Overall Confidence**: {{ overall_confidence }}

### Confidence Legend
- 🟢 HIGH (>85%): Extracted directly from paper text, verified
- 🟡 MEDIUM (50-85%): Extracted but may need human verification
- 🔴 LOW (<50%): Inferred or partially extracted, requires human completion
- ⬛ MISSING: Not found in paper, must be filled manually

---

## Generated Files

| File | Purpose | Confidence | Notes |
|------|---------|------------|-------|
{{ #each files }}
| `{{ path }}` | {{ purpose }} | {{ confidence }} | {{ notes }} |
{{ /each }}

---

## Human TODO Checklist

### 🔴 Critical (Must fix before running)

{{ #each critical_todos }}
- [ ] {{ description }}
  - Source: {{ source }}
  - What to do: {{ action }}
{{ /each }}

### 🟡 Important (Likely needs adjustment)

{{ #each important_todos }}
- [ ] {{ description }}
  - Source: {{ source }}
  - What to do: {{ action }}
{{ /each }}

### 🟢 Nice to have (Polish)

{{ #each optional_todos }}
- [ ] {{ description }}
{{ /each }}

---

## Extracted Formulas

{{ #each formulas }}
### {{ id }}: {{ description }}

```latex
{{ latex }}
```

- Source: {{ source }}
- Confidence: {{ confidence }}
- Implementation status: {{ impl_status }}
{{ #if needs_vision }}
- ⚠️ Formula extracted from PDF text — may contain errors. Verify against original PDF.
{{ /if }}

{{ /each }}

---

## Extracted Hyperparameters

| Parameter | Value | Source | Confidence |
|-----------|-------|--------|------------|
{{ #each hyperparameters }}
| {{ name }} | {{ value }} | {{ source }} | {{ confidence }} |
{{ /each }}

---

## Datasets

{{ #each datasets }}
### {{ name }}
- **Role**: {{ role }}
- **URL**: {{ url }}
- **Description**: {{ description }}
- **Availability**: {{ availability }}
{{ /each }}

---

## What This Scaffold Does NOT Cover

1. **Actual training execution** — This is a code skeleton. You need GPU resources to train.
2. **Exact numerical reproduction** — Random seeds, hardware differences, and library versions
   can cause small numerical differences.
3. **Undocumented tricks** — Papers sometimes omit implementation details that are critical
   for achieving reported numbers (e.g., gradient clipping, warmup schedule details).
4. **Data preprocessing edge cases** — Custom preprocessing that's described vaguely
   (e.g., "standard preprocessing") is filled with common defaults.

---

*This report was auto-generated. Always cross-reference with the original paper.*
