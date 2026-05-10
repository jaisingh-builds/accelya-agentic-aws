"""
weak_validator/handler.py — DO NOT MODIFY. This is the trainer-provided anti-example.

This handler exhibits all 6 Concept-5 failure modes from Day 3:
  1. Hallucinated APIs / fields
  2. Wrong field names / generic vocabulary
  3. Missing error paths
  4. Over-abstraction
  5. Silent swallow
  6. Cost-blind

Lab 3 work: score this artefact on the 5-dim HITL checklist (expect ~5/15),
then write a v2 prompt (prompts/v2_validator.txt) that closes the failure modes,
re-run Cascade, and compare to src/strong_validator/handler.py.
"""
import os
import json
import boto3

# Failure-mode 4 — over-abstraction: 4 levels of indirection for a 30-line problem.
# A "factory" that returns a "factory" returning a class…
class HandlerFactoryProvider:
    @staticmethod
    def get_factory():
        return HandlerFactory()


class HandlerFactory:
    def create_handler(self):
        return ValidatorHandlerBase()


class ValidatorHandlerBase:
    def __init__(self):
        self.s3 = boto3.client("s3")        # Failure-mode 6: client built per-cold-start, never reused properly
        self.bedrock = boto3.client("bedrock-runtime")    # ditto

    def process(self, event, context):
        return _process_event_internal(event, context, self.s3, self.bedrock)


def _process_event_internal(event, context, s3, bedrock):
    """Inner function the factory ultimately calls. Three levels deep."""

    bucket = os.environ.get("BUCKET", "accelya-airline-data-ap-south-1")

    try:
        # Failure-mode 2 — generic vocabulary:
        # uses order_id, transaction_amount, user_email (forbidden by programme contract)
        records = event.get("Records", [])
        results = []

        for rec in records:
            key = rec["s3"]["object"]["key"]
            obj = s3.get_object(Bucket=bucket, Key=key)
            body = obj["Body"].read()                # Failure-mode 4 / 3 — unbounded memory; loads entire file
            data = json.loads(body)

            # Failure-mode 6 — cost-blind:
            # Synchronous Bedrock call PER ROW. For a 10K-row file that's 10K invocations.
            # Programme cap is 50 invocations per session — would blow the budget.
            for row in data:
                response = bedrock.converse(
                    modelId="anthropic.claude-3-5-sonnet-20241022-v2:0",  # raw ID, not APAC profile
                    system=[{"text": "Classify this ticket issue."}],
                    messages=[{"role": "user", "content": [{"text": json.dumps(row)}]}],
                    inferenceConfig={"maxTokens": 200, "temperature": 0.0},
                )
                _ = response["output"]["message"]["content"][0]["text"]

                # Failure-mode 1 + 2 — hallucinated API + wrong field names:
                # boto3.client('s3') has no .save_validated_object() method.
                # Uses generic vocab: "order_id", "transaction_amount", "user_email".
                if "order_id" in row and "transaction_amount" in row:
                    s3.save_validated_object(             # HALLUCINATED — does not exist
                        Bucket=bucket,
                        Key="validated/" + row["order_id"] + ".json",
                        Body=json.dumps(row),
                    )
                    results.append({"order_id": row["order_id"], "status": "ok"})

        return {"statusCode": 200, "results": results}

    # Failure-mode 5 — silent swallow:
    # Bare except: pass. No log line. No re-raise. No quarantine write.
    # Schema-fail rows just disappear — no audit, no notification.
    except Exception:
        pass

    # Failure-mode 3 — missing error path:
    # If an exception was swallowed, we still return 200. Downstream thinks success.
    return {"statusCode": 200, "results": []}


# Entry point — Lambda invokes lambda_handler. Bury the actual work behind the factory.
def lambda_handler(event, context):
    """Lambda entry. Walks 4 levels of indirection before any real work."""
    factory_provider = HandlerFactoryProvider()
    factory = factory_provider.get_factory()
    handler = factory.create_handler()
    return handler.process(event, context)
