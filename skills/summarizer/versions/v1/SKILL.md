---
name: summarizer
description: >
  Summarise the results from planner if required and token limit is crossed.
version: v1
tools: []
judge:
  rubric:
    constraints: 0.40
    tool_use: 0.00
    grounding: 0.25
    helpfulness: 0.35
  rules:
    confidence_min: 0.55
---

# Summarizer

Summarise the results from planner if required and token limit is crossed.

## When to Use

USE this skill when:
- The output from the planner exceeds the token limit.
- A concise summary is needed to fit within constraints.

## When NOT to Use

DON'T use this skill when:
- The planner's output is already within the token limit.

## Constraints

- MUST maintain the key points and essential information in the summary.
- MUST ensure the summary fits within the specified token limit.
- NEVER omit critical information that changes the meaning of the original output.

## Output Format

Respond with ONLY a JSON object:
{
  "summary": "string" // The summarized version of the planner's output.
}

## Examples

Query: "Summarize the planner's detailed report on project milestones where the token limit is exceeded."
Expected output:
{
  "summary": "The project milestones include phases like planning, execution, and closure with key deadlines outlined for each phase."
}

Query: "Provide a summary of the extensive feedback received from the client meeting that crossed the token limit."
Expected output:
{
  "summary": "Client expressed satisfaction with current progress but highlighted concerns about delivery timelines and requested more frequent updates."
}