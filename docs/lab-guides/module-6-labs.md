# Module 6 — Lab Guides (Standalone Reference)

> The Day 6 deck has these labs on slides 20-29; this file is your standalone reference.

---

## Day 6 prerequisites

```bash
cd accelya-agentic-aws
git checkout main && git pull --ff-only
git checkout -b module-6-<your-name>

export LEARNER=<your-name>
export AWS_REGION=ap-south-1
export BUCKET=accelya-airline-data-ap-south-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# AWSSDKPandas layer (trainer provides this ARN at start-of-day)
export PANDAS_LAYER_ARN=arn:aws:lambda:ap-south-1:336392948345:layer:AWSSDKPandas-Python312:24

# Day 5 outputs must exist
aws s3 ls s3://$BUCKET/validated/$LEARNER/ --recursive --region $AWS_REGION | head -5

# Day 5 .windsurfrules v2 — confirm present
head -2 .windsurfrules    # should reference v2 and BATCH CONTEXT blocks
```

If `validated/$LEARNER/` is empty, you cannot run Day 6. Re-run your Day 5 pipeline first.

---

## Lab 1 — Provision 2 databases + 2 Crawlers + first run (45 min, SOLO)

**Deliverable:** `scripts/provision_m6_glue.sh` runs clean; `/reviews/m6-crawler-evidence.md` with 1st + 2nd JSON Crawler run output side-by-side; MR opened.

### Step 1 — Promote `.windsurfrules` v2 → v3 (CATALOG CONTEXT)

```bash
# The v3 template is in the starter repo
diff .windsurfrules docs/.windsurfrules-v3.template

# Copy the new CATALOG CONTEXT block between your BATCH CONTEXT and EXAMPLES.
# Easiest: replace the whole file.
cp docs/.windsurfrules-v3.template .windsurfrules

git add .windsurfrules
git commit -m "module-6: promote .windsurfrules v2 → v3 (CATALOG CONTEXT)"
```

### Step 2 — Provision Glue resources

```bash
bash scripts/provision_m6_glue.sh $LEARNER
```

The script creates: IAM role, 4 Glue databases (2 active, 2 scaffold-only), 2 Crawlers (JSON + Parquet). Idempotent; safe to re-run.

Verify:

```bash
aws glue get-databases --region $AWS_REGION \
  --query "DatabaseList[?contains(Name,'$LEARNER')].Name" --output table

aws glue get-crawlers --region $AWS_REGION \
  --query "Crawlers[?contains(Name,'$LEARNER')].[Name,State]" --output table
```

Expected: 4 databases, 2 Crawlers in `READY` state.

### Step 3 — Re-stage Day 5 output into Hive-style paths

Day 5's validator wrote `validated/<learner>/<bsp_cycle>/<chunk>.jsonl`. For the JSON Crawler to discover `source_system` and `ingest_date` as partition keys, we need Hive paths like `validated/<learner>/validated_settlement_json/source_system=BSP/ingest_date=2026-05-09/`.

```bash
# List what Day 5 produced (group by bsp_cycle)
aws s3 ls s3://$BUCKET/validated/$LEARNER/ --recursive --region $AWS_REGION | head -5

# Copy/re-stage. Adjust SOURCE + DATE as needed for your data.
SOURCE=BSP
DATE=2026-05-09

# For each Day-5 chunk file, copy into the Hive path
for KEY in $(aws s3 ls s3://$BUCKET/validated/$LEARNER/2026-W19/ --region $AWS_REGION \
              | awk '{print $4}' | grep -v '_manifests'); do
  aws s3 cp \
    s3://$BUCKET/validated/$LEARNER/2026-W19/$KEY \
    s3://$BUCKET/validated/$LEARNER/validated_settlement_json/source_system=$SOURCE/ingest_date=$DATE/$KEY \
    --region $AWS_REGION
done

# Verify the new paths
aws s3 ls s3://$BUCKET/validated/$LEARNER/validated_settlement_json/source_system=$SOURCE/ingest_date=$DATE/ \
  --region $AWS_REGION
```

### Step 4 — Run JSON Crawler (first run)

```bash
aws glue start-crawler --name validated-json-crawler-$LEARNER --region $AWS_REGION

# Poll until READY (~2-4 min)
while true; do
  STATE=$(aws glue get-crawler --name validated-json-crawler-$LEARNER --region $AWS_REGION \
    --query 'Crawler.State' --output text)
  echo "Crawler state: $STATE"
  [[ "$STATE" == "READY" ]] && break
  sleep 15
done

# Inspect discovered table
aws glue get-tables --database-name accelya_validated_$LEARNER --region $AWS_REGION \
  --query 'TableList[].[Name,StorageDescriptor.Location,PartitionKeys[].Name]' --output table

# Verify partition discovered
aws glue get-partitions --database-name accelya_validated_$LEARNER \
  --table-name validated_settlement_json --region $AWS_REGION \
  --query 'Partitions[].Values' --output table
```

Expected: table `validated_settlement_json` with 14 columns + 2 partition keys (`source_system`, `ingest_date`); 1 partition (`[BSP, 2026-05-09]`).

### Step 5 — Drop a NEW partition + rerun JSON Crawler

Drop one of your Day-5 chunk files into a *new* partition (different date), then rerun.

```bash
NEW_DATE=2026-05-10
SOURCE_FILE=$(aws s3 ls s3://$BUCKET/validated/$LEARNER/validated_settlement_json/source_system=$SOURCE/ingest_date=$DATE/ \
                --region $AWS_REGION | awk '{print $4}' | head -1)
aws s3 cp \
  s3://$BUCKET/validated/$LEARNER/validated_settlement_json/source_system=$SOURCE/ingest_date=$DATE/$SOURCE_FILE \
  s3://$BUCKET/validated/$LEARNER/validated_settlement_json/source_system=$SOURCE/ingest_date=$NEW_DATE/$SOURCE_FILE \
  --region $AWS_REGION

aws glue start-crawler --name validated-json-crawler-$LEARNER --region $AWS_REGION
# Wait for READY again
while true; do
  STATE=$(aws glue get-crawler --name validated-json-crawler-$LEARNER --region $AWS_REGION \
    --query 'Crawler.State' --output text)
  [[ "$STATE" == "READY" ]] && break
  sleep 15
done

# Should now show TWO partitions
aws glue get-partitions --database-name accelya_validated_$LEARNER \
  --table-name validated_settlement_json --region $AWS_REGION \
  --query 'Partitions[].Values' --output table
```

Expected: 2 partitions, no schema change.

### Step 6 — Document evidence + commit

```bash
nano reviews/m6-crawler-evidence.md
# Capture: 1st-run output, 2nd-run output, total columns count, partition count.

# Pickup test for .windsurfrules v3
# In a FRESH Cascade chat:
#   "Write me a SQL query to get total fare_amount by airline for 2026-05-09."
# Expected: references accelya_curated_<learner>.settlement (NOT the JSON table);
#           includes WHERE ingest_date='2026-05-09'; named columns, no SELECT *.

git add scripts/provision_m6_glue.sh reviews/m6-crawler-evidence.md
git commit -m "module-6: provision Glue catalog + first Crawler runs (Lab 1)"
git push -u origin module-6-$LEARNER
```

### Lab 1 common gotchas

- **Crawler scope too broad** — `Targets.S3Targets.Path` must be `validated/<learner>/validated_settlement_json/`, NEVER `validated/`. Slide 32 Mistake #3.
- **Non-Hive paths** — copying without `source_system=BSP/ingest_date=YYYY-MM-DD/` structure means Crawler discovers no partition keys.
- **Single Crawler swap-in-place** — don't re-target the JSON Crawler at the Parquet table. Lab 2's A/B comparison needs both tables alive.
- **`SchemaChangePolicy` defaults** — if you create a Crawler in the AWS console without explicit policy, `DeleteBehavior=DELETE_FROM_DATABASE` is set; Lab 3 will fail. The `provision_m6_glue.sh` script forces `UPDATE_IN_DATABASE / LOG`.

---

## Lab 2 — ETL Lambda + Athena workgroup + 5 reconciliation queries + A/B (45 min, PAIRS)

**Deliverable:** ETL Lambda deployed (6 of 10 cumulative); `accelya_curated_<learner>.settlement` Parquet table populated; Athena workgroup with cost cap; `/sql/m6-reconciliation-5.sql` all 5 queries SUCCEEDED; `/reviews/m6-query-cost-evidence.md` with JSON vs Parquet ratio ≥10×.

### Step 1 — Cascade scaffolds the ETL Lambda

Open a **fresh** Cascade chat. Prompt:

```
@cascade Read .windsurfrules. Using CATALOG CONTEXT, scaffold src/etl_json_to_parquet/handler.py:

- event in: { file_key, source_system, ingest_date, chunk_id }
- read JSONL from S3 (one row per line)
- normalise inbound: map 'amount' -> 'fare_amount' if present; drop _line_no
- cast to fixed PyArrow schema (settlement v3: 13 columns)
- write Parquet (Snappy) to curated/settlement/ingest_date=<>/source_system=<>/part-<chunk_id>.parquet
- return: { status, rows_in, rows_out, parquet_key, file_sha256_in, file_sha256_out }
- env vars: BUCKET_NAME, LEARNER
- raise SchemaInferenceError on cast failure (ASL Catch routes to QuarantineSchemaDrift)
- runtime python3.12 x86_64; memory 1024; timeout 180
- assume AWSSDKPandas layer provides pyarrow + pandas
- defer pyarrow imports inside handler() so module parses locally without the layer

Plus tests in tests/test_etl_json_to_parquet.py using moto for S3 + pyarrow inline.
```

Reference handler (compare to Cascade's output): `src/etl_json_to_parquet/handler.py`.

### Step 2 — Package + deploy ETL Lambda

```bash
# Build deployment zip (handler + common/exceptions; PyArrow comes from the layer)
rm -rf /tmp/m6-build && mkdir -p /tmp/m6-build/common
cp src/etl_json_to_parquet/handler.py /tmp/m6-build/
cp src/common/__init__.py             /tmp/m6-build/common/
cp src/common/exceptions.py           /tmp/m6-build/common/
( cd /tmp/m6-build && zip -qr /tmp/etl_json_to_parquet.zip . )

# Pipeline Lambda role from Day 5
PIPELINE_ROLE_ARN=$(aws iam get-role --role-name accelya-m5-pipeline-$LEARNER-role \
    --query 'Role.Arn' --output text)

aws lambda create-function \
  --function-name accelya-etl-json-to-parquet-$LEARNER \
  --runtime python3.12 \
  --architectures x86_64 \
  --handler handler.handler \
  --role $PIPELINE_ROLE_ARN \
  --memory-size 1024 --timeout 180 \
  --layers $PANDAS_LAYER_ARN \
  --zip-file fileb:///tmp/etl_json_to_parquet.zip \
  --environment "Variables={BUCKET_NAME=$BUCKET,LEARNER=$LEARNER}" \
  --region $AWS_REGION

aws lambda wait function-active-v2 \
  --function-name accelya-etl-json-to-parquet-$LEARNER --region $AWS_REGION
```

### Step 3 — Invoke ETL on one chunk

```bash
# Pick the first chunk from Lab 1's Hive-staged data
SAMPLE_KEY=$(aws s3 ls s3://$BUCKET/validated/$LEARNER/validated_settlement_json/source_system=BSP/ingest_date=2026-05-09/ \
              --region $AWS_REGION | awk '{print $4}' | head -1)

aws lambda invoke \
  --function-name accelya-etl-json-to-parquet-$LEARNER \
  --cli-binary-format raw-in-base64-out \
  --payload "{\"file_key\":\"validated/$LEARNER/validated_settlement_json/source_system=BSP/ingest_date=2026-05-09/$SAMPLE_KEY\",\"source_system\":\"BSP\",\"ingest_date\":\"2026-05-09\",\"chunk_id\":\"00001\"}" \
  --region $AWS_REGION \
  /tmp/etl-out.json

cat /tmp/etl-out.json | python3 -m json.tool
```

Expected: `status=converted`, `rows_in=rows_out`, `parquet_key` populated. Verify on S3:

```bash
aws s3 ls s3://$BUCKET/curated/settlement/ --recursive --region $AWS_REGION
```

### Step 4 — Run the Parquet Crawler

```bash
aws glue start-crawler --name curated-parquet-crawler-$LEARNER --region $AWS_REGION

# Wait
while true; do
  STATE=$(aws glue get-crawler --name curated-parquet-crawler-$LEARNER --region $AWS_REGION \
    --query 'Crawler.State' --output text)
  [[ "$STATE" == "READY" ]] && break
  sleep 15
done

# Inspect
aws glue get-tables --database-name accelya_curated_$LEARNER --region $AWS_REGION \
  --query 'TableList[].[Name,StorageDescriptor.SerdeInfo.SerializationLibrary]' --output table
```

Expected: table `settlement`, SerDe `org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe`.

### Step 5 — Create Athena workgroup with cost cap

```bash
aws athena create-work-group \
  --name accelya_$LEARNER \
  --configuration "ResultConfiguration={OutputLocation=s3://$BUCKET/athena-results/$LEARNER/},BytesScannedCutoffPerQuery=104857600,EnforceWorkGroupConfiguration=true,PublishCloudWatchMetricsEnabled=true" \
  --region $AWS_REGION

# Verify
aws athena get-work-group --work-group accelya_$LEARNER --region $AWS_REGION \
  --query 'WorkGroup.Configuration.[BytesScannedCutoffPerQuery,EnforceWorkGroupConfiguration]'
```

### Step 6 — Run 5 queries + capture A/B evidence

```bash
# Helper: run a query and capture DataScannedInBytes
run_query() {
  local SQL="$1" LABEL="$2"
  QID=$(aws athena start-query-execution \
    --query-string "$SQL" \
    --work-group accelya_$LEARNER \
    --region $AWS_REGION \
    --query QueryExecutionId --output text)
  # Wait
  while true; do
    STATE=$(aws athena get-query-execution --query-execution-id $QID --region $AWS_REGION \
      --query 'QueryExecution.Status.State' --output text)
    [[ "$STATE" =~ ^(SUCCEEDED|FAILED|CANCELLED)$ ]] && break
    sleep 2
  done
  BYTES=$(aws athena get-query-execution --query-execution-id $QID --region $AWS_REGION \
    --query 'QueryExecution.Statistics.DataScannedInBytes' --output text)
  TIME=$(aws athena get-query-execution --query-execution-id $QID --region $AWS_REGION \
    --query 'QueryExecution.Statistics.EngineExecutionTimeInMillis' --output text)
  echo "$LABEL  state=$STATE  bytes=$BYTES  time_ms=$TIME"
}

# Q1 on JSON
run_query "SELECT airline_code, COUNT(*), SUM(CAST(fare_amount AS DECIMAL(12,2))) \
FROM accelya_validated_$LEARNER.validated_settlement_json \
WHERE ingest_date='2026-05-09' AND source_system='BSP' \
GROUP BY airline_code" "Q1-JSON   "

# Q1 on Parquet
run_query "SELECT airline_code, COUNT(*), SUM(CAST(fare_amount AS DECIMAL(12,2))) \
FROM accelya_curated_$LEARNER.settlement \
WHERE ingest_date='2026-05-09' AND source_system='BSP' \
GROUP BY airline_code" "Q1-Parquet"
```

Run all 5 queries from `sql/m6-reconciliation-5.sql` (replace `<learner>` first). Capture each `DataScannedInBytes` to `/reviews/m6-query-cost-evidence.md`:

```
| Query | JSON bytes | Parquet bytes | Ratio |
|-------|------------|---------------|-------|
| Q1 (settlement-by-airline)  | 32145678 | 10485760 | 3.1×  |  ← Athena 10 MB minimum
| Q2 (missing-tickets)        | 32145678 | 10485760 | 3.1×  |
| ...
```

> Note: Athena reports `DataScannedInBytes` in 10 MB minimum increments. The actual scan on Parquet is ~1 MB. The *real* cost ratio is the bytes you'd be charged for at scale — typically 30-100× at our lab scale, 100-1000× on production-shape data.

```bash
git add src/etl_json_to_parquet/ sql/m6-reconciliation-5.sql \
        reviews/m6-query-cost-evidence.md tests/test_etl_json_to_parquet.py
git commit -m "module-6: ETL Lambda + Athena workgroup + 5 queries (Lab 2)"
git push
```

### Lab 2 common gotchas

- **`ModuleNotFoundError: pyarrow`** — forgot `--layers $PANDAS_LAYER_ARN`. Re-deploy with the flag.
- **Memory limit hit** — bump from 1024 MB only if file >50K rows; otherwise check for accidental `SELECT *` upstream.
- **Workgroup missing `EnforceWorkGroupConfiguration=true`** — learners can override the cap. Slide 25 mandates this flag.
- **`SELECT *` on the Parquet table** — workgroup blocks. Re-write with explicit columns.
- **Partition `ingest_date` typed as STRING** — Crawler default. Production may switch to DATE; lab keeps STRING for simplicity. Both work; just don't mix.

---

## Lab 3 — Schema evolution + workgroup cap firing (45 min, SOLO)

**Deliverable:** `/reviews/m6-schema-evolution.md` (Part A + theory fix); `/reviews/m6-workgroup-alarm-evidence.md` (Part B with FAILED state + ProcessedBytes metric); MR 3 commits.

### Part A — Additive schema evolution (~20 min)

```bash
# Step A1 — Get the synthetic additive-column test file
# (Trainer pre-staged this; ask if missing.)
aws s3 cp s3://$BUCKET/synthetic/m6-day3-bsp-additive.json /tmp/m6-additive.json --region $AWS_REGION
head -1 /tmp/m6-additive.json | python3 -m json.tool | head -20
# Expected: row contains all 13 original fields + `loyalty_program_id` (new).

# Step A2 — Upload to a NEW partition (do NOT invoke ETL — we want the JSON path to evolve)
aws s3 cp /tmp/m6-additive.json \
  s3://$BUCKET/validated/$LEARNER/validated_settlement_json/source_system=BSP/ingest_date=2026-05-11/m6-additive.json \
  --region $AWS_REGION

# Step A3 — Rerun the JSON Crawler
aws glue start-crawler --name validated-json-crawler-$LEARNER --region $AWS_REGION
# (poll until READY as before)

# Step A4 — Verify new column appears
aws glue get-table --database-name accelya_validated_$LEARNER \
  --name validated_settlement_json --region $AWS_REGION \
  --query 'Table.StorageDescriptor.Columns[].[Name,Type]' --output table
# Expected: 15 total columns (14 original + loyalty_program_id, typically STRING)

# Step A5 — Query: old partitions return NULL for new column
aws athena start-query-execution \
  --query-string "SELECT ingest_date, COUNT(*), COUNT(loyalty_program_id) AS with_loyalty \
                  FROM accelya_validated_$LEARNER.validated_settlement_json \
                  GROUP BY ingest_date \
                  ORDER BY ingest_date" \
  --work-group accelya_$LEARNER --region $AWS_REGION
# Expected: 2026-05-09 and 2026-05-10 → with_loyalty=0
#           2026-05-11                 → with_loyalty=N (number of rows in additive file)
```

Document in `reviews/m6-schema-evolution.md`:
- Before/after column count
- Query showing NULL on old partitions
- **ETL fix theory**: the current `SCHEMA = pa.schema([13 fields])` would silently drop `loyalty_program_id` on write. Fix: add `pa.field('loyalty_program_id', pa.string())` to SCHEMA, dual-write one cycle, re-deploy. Production pattern is documented in slide 11 Pattern #1 (additive).

### Part B — Workgroup cap firing (~15 min)

```bash
# Step B1 — Drop cap to 10 MB (Athena minimum)
aws athena update-work-group \
  --work-group accelya_$LEARNER \
  --configuration-updates 'BytesScannedCutoffPerQuery=10000000' \
  --region $AWS_REGION

# Verify
aws athena get-work-group --work-group accelya_$LEARNER --region $AWS_REGION \
  --query 'WorkGroup.Configuration.BytesScannedCutoffPerQuery'
# Expected: 10000000

# Step B2 — Run a deliberately bad query (no partition filter)
QID=$(aws athena start-query-execution \
  --query-string "SELECT * FROM accelya_validated_$LEARNER.validated_settlement_json" \
  --work-group accelya_$LEARNER \
  --region $AWS_REGION \
  --query QueryExecutionId --output text)
echo "Query ID: $QID"

# Wait for terminal state
sleep 10
aws athena get-query-execution --query-execution-id $QID --region $AWS_REGION \
  --query 'QueryExecution.[Status.State,Status.StateChangeReason,Statistics.DataScannedInBytes]' \
  --output text
# Expected:
#   State              FAILED  (or CANCELLED)
#   StateChangeReason  "Bytes scanned limit was exceeded ..."
#   DataScannedInBytes 10000001+

# Step B3 — Pull the CloudWatch ProcessedBytes metric
START=$(date -u -v-5M +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u --date='5 minutes ago' +%Y-%m-%dT%H:%M:%S)
END=$(date -u +%Y-%m-%dT%H:%M:%S)
aws cloudwatch get-metric-statistics \
  --namespace AWS/Athena \
  --metric-name ProcessedBytes \
  --dimensions Name=WorkGroup,Value=accelya_$LEARNER \
               Name=QueryState,Value=FAILED \
               Name=QueryType,Value=DML \
  --start-time $START --end-time $END --period 60 \
  --statistics Sum --region $AWS_REGION

# Step B4 — RESTORE the cap to 100 MB (critical — Day 7+ inherits this)
aws athena update-work-group \
  --work-group accelya_$LEARNER \
  --configuration-updates 'BytesScannedCutoffPerQuery=104857600' \
  --region $AWS_REGION
# Verify
aws athena get-work-group --work-group accelya_$LEARNER --region $AWS_REGION \
  --query 'WorkGroup.Configuration.BytesScannedCutoffPerQuery'
# Expected: 104857600
```

Document in `reviews/m6-workgroup-alarm-evidence.md`:
- Cap drop command + verify
- Failed query ID + `Status.StateChangeReason`
- CloudWatch `ProcessedBytes` output (the Sum value)
- Cap restored to 100 MB confirmation

### Step — Commit

```bash
git add reviews/m6-schema-evolution.md reviews/m6-workgroup-alarm-evidence.md
git commit -m "module-6: schema evolution + workgroup cap firing (Lab 3)"
git push
```

### Lab 3 common gotchas

- **Forgetting to restore cap** — Day 7 queries fail at 10 MB. The cleanup script `scripts/cleanup_module6.sh` restores it as a safety net, but you should restore it explicitly in Lab 3.
- **Wrong CloudWatch metric** — `CancelledQueryCount` doesn't exist. Use `ProcessedBytes` filtered by `QueryState` dimension.
- **Old partitions show data for `loyalty_program_id`** — you forgot to scope `WHERE` to new partition. Re-check Step A5.

---

## End-of-module cleanup

```bash
bash scripts/cleanup_module6.sh $LEARNER
```

The script preserves **everything Day 7 needs** (Lambda, both Crawlers, both databases, curated `settlement` table, Athena workgroup) and restores the cap to 100 MB if Lab 3 left it lower.

---

## Day 6 in numbers

| Metric | Value |
|---|---|
| Programme Lambdas | 6 of 10 (+1 ETL today) |
| Glue Databases | 4 (2 active, 2 scaffold) |
| Glue Tables active | 2 (`validated_settlement_json`, `settlement`) |
| Glue Crawlers | 2 |
| Glue DPU-h consumed | ≤1 of 6 |
| Athena workgroup | `accelya_<learner>` with 100 MB cap |
| Query cost reduction observed | ≥10× (10 MB billed minimum vs 100+ MB JSON); real ratio at scale ~100× |
| `.windsurfrules` version | v3 |
| HITL dimensions | 6 (Schema Discipline added) |
| AWS Bedrock invocations | ~0 today (cumulative ~2-5 of 50) |
| MR commits | 3 |

---

## What's coming on Day 7

Module 7 — **Streaming Architecture** (design-only). Zero new Lambdas. One Kinesis stream provisioned. `.windsurfrules` v3 → v4 adds `STREAM CONTEXT` block (shard count, partition key strategy, retention, replay window). Day 8 implements the streaming pipeline; it *reads* today's curated table for enrichment joins.

Bring tomorrow:
- Today's `curated/settlement/` Parquet data
- Today's Glue Catalog (`accelya_curated_<learner>.settlement`)
- Today's `.windsurfrules` v3
- ETL Lambda still alive

---

*See `Day6_Module6_DataTransform_Catalog_Analytics.pptx` slides 20-29 for the deck's full visual treatment.*
