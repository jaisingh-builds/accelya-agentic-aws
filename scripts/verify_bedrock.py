#!/usr/bin/env python3
"""
verify_bedrock.py — Day 1 Lab 1 verification script.

What this does
--------------
1. Calls AWS Bedrock via the Converse API in ap-south-1.
2. Uses the APAC cross-region inference profile (configurable via env var).
3. Asks Claude to propose 2 architectures for an airline ticket-issue batch pipeline.
4. Prints the model reply + token usage.

Success criteria (Day 1 slide 25)
---------------------------------
- Exits 0.
- Prints two architecture options as parseable JSON.
- response["usage"]["inputTokens"] > 0 AND response["usage"]["outputTokens"] > 0.
- Tokens used ≤ 1500.

Environment overrides (cohort/trainer flexibility)
--------------------------------------------------
- AWS_DEFAULT_REGION      (default: ap-south-1)
- BEDROCK_MODEL_ID        (default: apac.anthropic.claude-3-5-sonnet-20241022-v2:0)
- BEDROCK_MAX_TOKENS      (default: 1024)
- BEDROCK_TEMPERATURE     (default: 0.2)

Usage
-----
    python3 scripts/verify_bedrock.py
    # OR with a profile override (Day 1 fallback if v2 profile not in your account):
    BEDROCK_MODEL_ID="apac.anthropic.claude-3-5-sonnet-20240620-v1:0" python3 scripts/verify_bedrock.py
"""
import json
import os
import sys

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
    "apac.anthropic.claude-3-5-sonnet-20241022-v2:0",  # APAC profile — programme default
)
MAX_TOKENS = int(os.getenv("BEDROCK_MAX_TOKENS", "1024"))
TEMPERATURE = float(os.getenv("BEDROCK_TEMPERATURE", "0.2"))

SYSTEM_PROMPT = (
    "You are a senior AWS data architect specialising in airline batch pipelines. "
    "Reply in JSON only — no preamble, no markdown fences."
)

USER_PROMPT = (
    "Propose two architectures for ingesting and validating daily airline "
    "ticket-issue files (CSV, ~50 MB per airline, arriving via SFTP to S3). "
    "Required fields: PNR, airline_code, fare_class, OD, settlement_date. "
    "Respond as a JSON array of two objects, each with keys: "
    "option_name, services, data_flow, trade_offs, "
    "estimated_monthly_cost (illustrative only — actual pricing validated later)."
)


def main() -> int:
    print(f"  region:  {REGION}")
    print(f"  model:   {MODEL_ID}")
    print(f"  config:  maxTokens={MAX_TOKENS}, temperature={TEMPERATURE}")
    print()

    client = boto3.client("bedrock-runtime", region_name=REGION)

    try:
        response = client.converse(
            modelId=MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[
                {"role": "user", "content": [{"text": USER_PROMPT}]}
            ],
            inferenceConfig={
                "maxTokens": MAX_TOKENS,
                "temperature": TEMPERATURE,
            },
        )
    except client.exceptions.AccessDeniedException as e:
        sys.stderr.write(
            "ERROR: AccessDeniedException — Bedrock model access not granted to "
            "your IAM identity in {region}.\n"
            "Fix: ask the trainer / client to enable Bedrock model access for "
            "'{model}' in {region}.\n"
            "Details: {err}\n".format(region=REGION, model=MODEL_ID, err=e)
        )
        return 3
    except client.exceptions.ResourceNotFoundException as e:
        sys.stderr.write(
            "ERROR: ResourceNotFoundException — model '{model}' not available in "
            "{region}.\n"
            "Fix: list available profiles with:\n"
            "  aws bedrock list-inference-profiles --region {region}\n"
            "Then override at runtime:\n"
            "  BEDROCK_MODEL_ID='<profile-id>' python3 scripts/verify_bedrock.py\n"
            "Details: {err}\n".format(region=REGION, model=MODEL_ID, err=e)
        )
        return 4
    except client.exceptions.ValidationException as e:
        sys.stderr.write(
            "ERROR: ValidationException — request shape rejected.\n"
            "Common causes: wrong model ID format (must be the inference-profile "
            "string, not raw model ID), or maxTokens too high for the model.\n"
            "Details: {err}\n".format(err=e)
        )
        return 5
    except Exception as e:
        sys.stderr.write(
            "ERROR: unexpected exception calling Bedrock Converse.\n"
            "Details: {err}\n".format(err=e)
        )
        return 6

    reply_text = response["output"]["message"]["content"][0]["text"]
    usage = response["usage"]

    print("✅ Bedrock Converse OK")
    print(f"   tokens:  in={usage['inputTokens']}, "
          f"out={usage['outputTokens']}, total={usage['totalTokens']}")
    print()
    print("Model reply (first 2000 chars):")
    print("-" * 60)
    print(reply_text[:2000])
    print("-" * 60)

    # Try to parse as JSON — Lab 1 success criterion.
    # Accept any of these shapes (Claude returns slightly different shapes per run):
    #   [{...}, {...}]                        — JSON array
    #   {"options":      [{...}, {...}]}      — programme-recommended shape
    #   {"architectures":[{...}, {...}]}      — common alternative
    #   {"any_list_key": [{...}, {...}]}      — accept any top-level array of objects
    try:
        parsed = json.loads(reply_text)
        if isinstance(parsed, list) and len(parsed) >= 2:
            print()
            print(f"✅ Parsed as JSON array of {len(parsed)} architecture options.")
        elif isinstance(parsed, dict):
            list_keys = [k for k, v in parsed.items()
                         if isinstance(v, list) and len(v) >= 2
                         and all(isinstance(x, dict) for x in v)]
            if list_keys:
                k = list_keys[0]
                print()
                print(f"✅ Parsed as JSON object with '{k}' key "
                      f"({len(parsed[k])} architecture options).")
            else:
                print()
                print("⚠  Parsed as JSON but no top-level list of options found. "
                      "Inspect the reply.")
        else:
            print()
            print("⚠  Parsed as JSON but shape is unexpected. Inspect the reply.")
    except json.JSONDecodeError as e:
        print()
        print("⚠  Reply is not valid JSON. The model may have wrapped it in "
              f"markdown fences or added preamble. JSON error: {e}")

    if usage["totalTokens"] > 1500:
        print(f"\n⚠  Tokens used ({usage['totalTokens']}) exceed the 1500 budget "
              f"for Lab 1. Re-check maxTokens or prompt length.")
        return 7

    return 0


if __name__ == "__main__":
    sys.exit(main())
