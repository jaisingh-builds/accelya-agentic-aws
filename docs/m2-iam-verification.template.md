# Module 2 — Lab 1 IAM Verification

> **Template.** Copy this to `docs/m2-iam-verification.md` and fill in.
> Commit alongside your branch by end of Lab 1.

---

## Your identity

**ARN (redact account number):** `arn:aws:iam::***:user/accelya-learner-<your-name>`
**Identity type:** [ ] IAM user  [ ] Assumed role / federated  [ ] Other
**Region default:** `ap-south-1`
**Date verified:** YYYY-MM-DD

---

## Step 1 — Confirm identity

**Command:**
```bash
aws sts get-caller-identity --region ap-south-1
```

**Output (sanitised — redact account):**
```json
{
    "UserId": "AIDAEXAMPLE...",
    "Account": "***",
    "Arn": "arn:aws:iam::***:user/accelya-learner-<your-name>"
}
```

✓ Confirmed: my Arn ends with `accelya-learner-<your-name>`.

---

## Step 2 — Read identity + permission boundary

**Command run:**
```bash
aws iam get-user --user-name accelya-learner-<your-name>
```

(Or, if NoSuchEntity:)
```bash
aws iam get-role --role-name <role-from-sts-arn>
aws iam list-attached-role-policies --role-name <role-from-sts-arn>
```

**Boundary discovered:**
**PermissionsBoundary name:** `accelya-program-boundary`
**PermissionsBoundary ARN:** `arn:aws:iam::***:policy/accelya-program-boundary`

**Attached policies:**
- `<policy-1>` — gives me `<x, y, z>`
- `<policy-2>` — gives me `<a, b, c>`

---

## Step 3 — Probe an ALLOWED action

**Command:**
```bash
aws s3 ls s3://accelya-airline-data-ap-south-1/raw/ --region ap-south-1
```

**Output (first 5 lines):**
```
                           PRE AI/
                           PRE BA/
                           PRE EK/
                           PRE LH/
                           PRE SQ/
```

✓ Verdict: my role can read `raw/`. Five airline subfolders visible. No `AccessDeniedException`.

---

## Step 4 — Probe a DENIED action

**Command:**
```bash
aws iam create-user --user-name should-fail
```

**Output (exact error message):**
```
An error occurred (AccessDeniedException) when calling the CreateUser operation:
User: arn:aws:iam::***:user/accelya-learner-<your-name> is not authorized to perform:
iam:CreateUser on resource: arn:aws:iam::***:user/should-fail with an explicit deny
in a permissions boundary
```

✓ Verdict: boundary works. `iam:CreateUser` denied. My identity cannot escalate to admin even if a future policy attached `iam:*`.

---

## What the boundary protects me from (in my own words)

The `accelya-program-boundary` is the **maximum-allowed** ceiling on my identity. Even if a future policy (mine or one Cascade generates) says I can do `iam:*`, the boundary clamps it to its allow-list. This protects the programme against:

- Accidental escalation if Cascade hallucinates an IAM-creating Lambda.
- Compromised credentials being used to create new identities (the most common AWS breach path).
- Drift between intended permissions and actual permissions over the 12-day programme.

---

## Findings I'd flag for review

(Optional — leave blank if none.)

- [ ] I noticed `<something interesting about my IAM>`. Asking trainer to confirm intent.
- [ ] `<other observation>`

---

*Source: Day 2 Lab 1 (deck slides 20-22). HITL Security dimension: this is the evidence file you commit.*
