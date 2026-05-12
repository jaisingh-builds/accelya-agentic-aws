#!/usr/bin/env python3
"""
generate_architectures.py — Day 3 Lab 2 reference script.

What it does
------------
1. Reads prompts/v1_arch_options.txt (your 5-section prompt for architecture options).
2. Calls AWS Bedrock via the Converse API in ap-south-1.
3. Uses the APAC inference profile (configurable via env var).
4. Parses the JSON response using strip_fences() for robustness against ```json fences.
5. Asserts the response contains 2-3 options.
6. FLAGS (does not crash) options with sandbox_compatible=False.
7. Writes outputs/m3-arch-options.json.

This file is the trainer-provided reference. Lab 2 step 1 asks learners to
Cascade-author their own version against Concept 4 of the Day 3 deck — they
can compare to this reference once they've written theirs.

Usage
-----
    python3 scripts/generate_architectures.py

Environment overrides
---------------------
- AWS_DEFAULT_REGION      (default: ap-south-1)
- BEDROCK_MODEL_ID        (default: apac.anthropic.claude-3-5-sonnet-20241022-v2:0)
- BEDROCK_MAX_TOKENS      (default: 2000)
- BEDROCK_TEMPERATURE     (default: 0.2)
- PROMPT_PATH             (default: prompts/v1_arch_options.txt)
- OUTPUT_PATH             (default: outputs/m3-arch-options.json)
"""
import json
import os
import re
import sys
from pathlib import Path

try:
    import boto3
except ImportError:
    sys.stderr.write(
        "ERROR: boto3 is not installed.\n"
        "Fix: python3 -m pip install -U boto3\n"
    )
    sys.exit(2)

REGION = os.getenv("AWS_DEFAULT_REGION", "ap-south-1")
MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID",
    "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",
)
MAX_TOKENS = int(os.getenv("BEDROCK_MAX_TOKENS", "2000"))
TEMPERATURE = float(os.getenv("BEDROCK_TEMPERATURE", "0.2"))
PROMPT_PATH = Path(os.getenv("PROMPT_PATH", "prompts/v1_arch_options.txt"))
OUTPUT_PATH = Path(os.getenv("OUTPUT_PATH", "outputs/m3-arch-options.json"))


def strip_fences(s: str) -> str:
    """
    Robust JSON-fence cleanup. Handles:
      - leading whitespace
      - ```json or ``` opening fence
      - ``` closing fence
      - prose preamble/postamble (falls back to first { and last })
    """
    s = s.strip()
    s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
    s = re.sub(r"\n?```\s*$", "", s).strip()
    if not s.startswith("{"):
        first = s.find("{")
        last = s.rfind("}")
        if first >= 0 and last > first:
            s = s[first:last + 1]
    return s.strip()


def main() -> int:
    if not PROMPT_PATH.exists():
        sys.stderr.write(f"ERROR: prompt not found at {PROMPT_PATH}\n")
        sys.stderr.write(f"       Author it in Lab 1 step 3 (see Day 3 deck slide 21).\n")
        return 3

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    prompt = PROMPT_PATH.read_text()
    print(f"  region:  {REGION}")
    print(f"  model:   {MODEL_ID}")
    print(f"  prompt:  {PROMPT_PATH} ({len(prompt)} chars)")
    print(f"  output:  {OUTPUT_PATH}")
    print()

    client = boto3.client("bedrock-runtime", region_name=REGION)

    try:
        response = client.converse(
            modelId=MODEL_ID,
            system=[{"text": "Output JSON only; no prose; no markdown fences."}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={
                "maxTokens": MAX_TOKENS,
                "temperature": TEMPERATURE,
            },
        )
    except client.exceptions.AccessDeniedException as e:
        sys.stderr.write(f"ERROR: AccessDeniedException — {e}\n")
        sys.stderr.write("Fix: ask trainer to enable Bedrock model access for "
                         f"'{MODEL_ID}' in {REGION}.\n")
        return 4
    except client.exceptions.ResourceNotFoundException as e:
        sys.stderr.write(f"ERROR: model not found in {REGION}: {e}\n")
        sys.stderr.write(f"Fix: aws bedrock list-inference-profiles --region {REGION}\n")
        return 5
    except Exception as e:
        sys.stderr.write(f"ERROR: Bedrock call failed: {e}\n")
        return 6

    raw = response["output"]["message"]["content"][0]["text"]
    usage = response["usage"]

    print("✅ Bedrock Converse OK")
    print(f"   tokens: in={usage['inputTokens']}, out={usage['outputTokens']}, "
          f"total={usage['totalTokens']}")
    print()

    # Parse with strip_fences() for robustness
    try:
        parsed = json.loads(strip_fences(raw))
    except json.JSONDecodeError as e:
        sys.stderr.write(f"ERROR: JSON parse failed: {e}\n")
        sys.stderr.write("Raw response (first 1000 chars):\n")
        sys.stderr.write(raw[:1000] + "\n")
        return 7

    # Expect { "options": [...] } or top-level list
    if isinstance(parsed, dict) and "options" in parsed:
        options = parsed["options"]
    elif isinstance(parsed, list):
        options = parsed
    else:
        sys.stderr.write(f"ERROR: unexpected response shape: {type(parsed).__name__}\n")
        return 8

    if not (2 <= len(options) <= 3):
        sys.stderr.write(
            f"WARN: expected 2-3 options, got {len(options)}. "
            "Continuing — review the prompt to constrain the count.\n"
        )

    # FLAG (don't crash) options that are sandbox-incompatible
    print(f"Architecture options returned: {len(options)}")
    for i, opt in enumerate(options, start=1):
        name = opt.get("name", f"option-{i}")
        compat = opt.get("sandbox_compatible", "unknown")
        if compat is False:
            opt["DISQUALIFIED"] = (
                "sandbox_compatible=False — exclude from shortlist; scorecard disqualifies"
            )
            flag = "  [DISQUALIFIED]"
        else:
            flag = ""
        services = ", ".join(opt.get("services", []))[:60]
        print(f"  {i}. {name} (sandbox: {compat}){flag}")
        print(f"     services: {services}")

    # Write the output JSON
    OUTPUT_PATH.write_text(json.dumps(options, indent=2))
    print()
    print(f"✓ Wrote {OUTPUT_PATH}")
    print()
    print("Next: score each option on the 5-dim scorecard (reviews/m3-arch-scorecard.csv).")
    print("      Decision MR: reviews/m3-arch-decision-MR.md")

    return 0


if __name__ == "__main__":
    sys.exit(main())
