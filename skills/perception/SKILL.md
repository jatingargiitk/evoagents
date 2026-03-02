---
name: perception
description: >
  Analyze the user's question and extract structured information
  for downstream planning.
version: v1
tools: []
judge:
  rubric:
    constraints: 0.35
    tool_use: 0.05
    grounding: 0.20
    helpfulness: 0.40
  rules:
    confidence_min: 0.55
---

# Perception Skill

Analyze the user's question and extract structured information for downstream planning.

## When to Use

USE this skill when:
- A new user question arrives and needs to be analyzed
- Downstream skills need structured context about the query

## When NOT to Use

DON'T use this skill when:
- The question has already been analyzed by a prior perception pass

## Constraints

- MUST output valid JSON matching the Output Format schema
- MUST set recency_required to true if the question asks about recent, current, or time-sensitive information
- MUST identify all key entities and topics in the question
- MUST include temporal/recency keywords (e.g. "latest", "recent", "2025", "current", "today") as entities when present in the question
- NEVER include speculation about the answer — only analyze the question itself

## Output Format

Respond with ONLY a JSON object:
```json
{
  "intent": "What the user wants to know (1 sentence)",
  "entities": ["key entities", "topics", "concepts"],
  "constraints": ["time range", "domain", "format constraints"],
  "recency_required": true,
  "complexity": "simple | moderate | complex"
}
```

## Examples

Query: "What happened in AI this week?"
Expected output:
```json
{
  "intent": "Find recent AI news and developments from the past week",
  "entities": ["artificial intelligence", "AI news", "this week"],
  "constraints": ["time range: past week"],
  "recency_required": true,
  "complexity": "moderate"
}
```

Query: "What are the latest breakthroughs in quantum computing in 2025?"
Expected output:
```json
{
  "intent": "Find the most recent quantum computing advances in 2025",
  "entities": ["quantum computing", "breakthroughs", "latest", "2025"],
  "constraints": ["time range: 2025", "domain: quantum computing"],
  "recency_required": true,
  "complexity": "moderate"
}
```

Query: "Explain how gradient descent works"
Expected output:
```json
{
  "intent": "Explain the gradient descent optimization algorithm",
  "entities": ["gradient descent", "optimization", "machine learning"],
  "constraints": [],
  "recency_required": false,
  "complexity": "moderate"
}
```
