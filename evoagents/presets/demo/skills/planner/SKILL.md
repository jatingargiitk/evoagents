---
name: planner
description: >
  Plans research steps and gathers information using tools.
  Use when the user asks a research question that needs information gathering.
version: v1
tools:
  - web_search
  - http_get
requires:
  tools: [web_search]
judge:
  rubric:
    constraints: 0.30
    tool_use: 0.30
    grounding: 0.25
    helpfulness: 0.15
  rules:
    confidence_min: 0.55
---

# Planner Skill

Plan research steps and gather information for the user's question.

## When to Use

USE this skill when:
- User asks about recent events, current status, trends
- Question requires up-to-date information
- Research or multi-step information gathering is needed

## When NOT to Use

DON'T use this skill when:
- Simple factual question answerable from general knowledge
- User is asking for an opinion or creative writing

## Constraints

- MUST actually invoke tools via function calling, not just describe them
- NEVER provide outdated info when tools are available to get current data

## Tools

### web_search
Search the web for current information.
**When to call:** Any query where web results could help.

### http_get
Fetch content from a specific URL.
**When to call:** When you have a specific URL to retrieve.

## Output Format

After using any necessary tools, respond with JSON:
```json
{
  "plan": ["step 1", "step 2"],
  "tools_used": ["web_search"],
  "findings": "summary of gathered information",
  "reasoning": "why this approach"
}
```

## Examples

Query: "Explain how neural networks work"
Expected: Answer from knowledge, no tool calls needed.
