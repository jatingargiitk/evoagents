---
name: synthesizer
description: >
  Produces a final comprehensive answer based on all gathered research.
version: v1
tools: []
judge:
  rubric:
    constraints: 0.25
    tool_use: 0.10
    grounding: 0.40
    helpfulness: 0.25
  rules:
    confidence_min: 0.55
---

# Synthesizer Skill

Produce a final, comprehensive answer based on all gathered research.

## When to Use

USE this skill when:
- Upstream skills have gathered research and evidence
- A final answer needs to be assembled from multiple sources

## When NOT to Use

DON'T use this skill when:
- No prior research has been done
- The question requires direct tool usage (use planner instead)

## Constraints

- MUST produce a clear, accurate, and helpful answer
- MUST use information provided by earlier pipeline steps

## Output Format

Respond with a JSON object:
```json
{
  "answer": "Your comprehensive answer here.",
  "confidence": "high | medium | low"
}
```

## Examples

Given planner findings about "latest AI news":
Expected: A well-structured summary of the findings.
