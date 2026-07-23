# AIOps Presentation — 3 Slides + Live Demo Guide

> **Purpose:** Introduce AIOps to learners before the live hands-on demo  
> **Duration:** 10 minutes (slides) + 15 minutes (live demo)  
> **Audience:** DevOps engineers who know basic K8s/AWS, want to add AI skills

---

## Slide 1: "The Evolution — From Scripts to AI"

**Title:** DevOps Evolution: Scripts → Platforms → AI Agents

```
2015-2018                    2019-2022                    2023-2026
─────────                    ─────────                    ─────────

AUTOMATION ERA               PLATFORM ERA                 AI/LLM ERA

Shell Scripts                Self-Service Portals         LLM-Powered Agents
Ansible Playbooks            Internal Dev Platforms       Auto-Remediation
Cron Jobs                    Backstage / Port             Bedrock / GPT Agents
Jenkins Pipelines            GitOps + ArgoCD              AIOps Self-Healing

"Automate repeatable        "Let developers help         "Let AI handle the
 tasks so humans don't       themselves — reduce          2AM incidents —
 have to do them twice"      ticket queues to zero"       humans sleep"

WHO DOES THE WORK:           WHO DOES THE WORK:           WHO DOES THE WORK:
DevOps engineer writes       Platform team builds         AI agent watches,
scripts, runs them           portal, devs self-serve      diagnoses, and ACTS
manually or via cron                                      autonomously
```

**Talking Points:**
- Each era didn't replace the previous one — it built ON TOP of it
- You still need scripts. You still need platforms. But now we add an AI layer that uses those same tools AUTONOMOUSLY
- The engineer's role shifted: from "doing the work" → "building the system that does the work" → "building the AI that decides what work to do"

---

## Slide 2: "LLMs in DevOps — Real Use Cases TODAY"

**Title:** How LLMs Are Already Automating DevOps Work

```
┌────────────────────────────────────────────────────────────────────┐
│  LLM + DevOps = Less Toil, Faster Response, Zero 2AM Wake-Ups     │
└────────────────────────────────────────────────────────────────────┘
```

### USE CASE 1: JITA (Just-In-Time Access) Bot

```
Developer: "I need access to prod RDS for 2 hours to debug issue #452"

LLM Bot:   → Validates the request (checks JIRA ticket exists)
           → Checks org policy (max 4 hours for prod DB)
           → Grants access via AWS IAM (temporary credentials)
           → Auto-revokes after 2 hours
           → Logs everything to audit trail

No human approver needed at 2 AM.
```

**How it works behind the scenes:**
- Slack bot receives request
- LLM (Bedrock) parses intent + extracts parameters
- Validates against policy engine (OPA / Cedar)
- Calls AWS API (STS assume-role, time-boxed)
- K8s pod running the bot uses IRSA for AWS access

### USE CASE 2: Auto Access Granting (Jenkins, GitHub, AWS)

```
New joiner: "Add me to team-backend repos and Jenkins pipelines"

LLM Bot:   → Reads HR system (confirms team = backend)
           → Grants GitHub team membership
           → Adds Jenkins folder permissions
           → Creates AWS SSO assignment
           → Sends onboarding checklist to Slack

1 day process → 5 minutes. Zero tickets.
```

**How it works behind the scenes:**
- LLM understands natural language request
- Maps to predefined actions (GitHub API, Jenkins API, AWS SSO API)
- Runs approval workflow if needed (manager notification)
- All actions are audited and reversible

### USE CASE 3: AIOps Self-Healing (OUR PROJECT)

```
3 AM:      Pod crashes → CrashLoopBackOff

AI Agent:  → Reads K8s events + pod logs
           → Sends to Bedrock: "What's wrong? What should I do?"
           → Bedrock: "OOMKilled. Restart will work after GC."
           → Agent restarts pod → verifies health → logs incident
           → Morning: engineer sees "Incident auto-resolved at 3:02 AM"

Nobody woke up. Service was down for 90 seconds, not 30 minutes.
```

**Talking Points:**
- The pattern is always the same: LLM understands context → makes a decision → takes an action → logs it
- The pod behind the scenes is just a K8s deployment with IRSA accessing Bedrock
- That's what we'll build today

---

## Slide 3: "What We're Building — Live Demo Preview"

**Title:** AIOps Self-Healing Agent — Architecture & Live Demo

```
     YOUR EKS CLUSTER
     ┌──────────────────────────────────────────────────────┐
     │                                                       │
     │  ┌─────────────┐          ┌─────────────────────┐    │
     │  │ aiops-agent │──watch──→│ auth-service (dev)   │    │
     │  │ (Python pod)│          │ (deliberately broken)│    │
     │  └──────┬──────┘          └─────────────────────┘    │
     │         │                                             │
     │         │ 1. Detect CrashLoopBackOff                  │
     │         │ 2. Read pod logs via K8s API                │
     │         │ 3. Send to Bedrock (IRSA, no keys!)         │
     │         │ 4. Get root cause + action                  │
     │         │ 5. Auto-restart pod                         │
     │         │ 6. Verify health ✅                          │
     │         │                                             │
     └─────────┼─────────────────────────────────────────────┘
               │
               ▼
     ┌──────────────────┐
     │  AWS Bedrock      │
     │  (Claude Haiku)   │
     │                   │
     │  "Root cause:     │
     │   OOMKilled.      │
     │   Action: RESTART"│
     └──────────────────┘
```

**What makes this production-grade (not a toy demo):**

| Aspect | Our Implementation |
|---|---|
| Auth to AWS | IRSA (no static keys, short-lived tokens) |
| Log access | K8s API (real-time, direct from kubelet) |
| AI model | AWS Bedrock (enterprise, no data leaves your account) |
| Safety | Guardrails: auto-fix in dev, alert-only in prod |
| Deployment | GitOps via ArgoCD (same as all other services) |
| Observability | Prometheus metrics (incidents_total, mttr_seconds) |

**Talking Points:**
- This is not a demo app — this is the same pattern Netflix, Uber, and AWS use internally
- IRSA for security, K8s API for observability, Bedrock for intelligence, guardrails for safety
- In prod it only alerts — in dev it fixes. That's the real-world pattern

---

## Live Demo Script (After Slides)

**Total time:** 15 minutes

### Step 1: Show Healthy Cluster (2 min)

```bash
# "Here's our cluster — 2 nodes, healthy"
kubectl get nodes
kubectl get pods -n dev

# "Our agent is running, watching for failures"
kubectl logs deployment/aiops-agent -n dev --tail=5
```

**Say:** "Everything is green. The agent is running, checking every 30 seconds. Nothing to do — boring. Let's break something."

### Step 2: Break Auth-Service (1 min)

```bash
# "I'm going to simulate a bad deployment — wrong image tag"
kubectl set image deployment/auth-service auth-service=nginx:doesnotexist -n dev

# "Watch it fail"
kubectl get pods -n dev -w
```

**Say:** "This is what happens at 3 AM when someone pushes a bad image. Pod goes into ImagePullBackOff. Normally, PagerDuty wakes you up. But we have an agent..."

### Step 3: Watch Agent Detect & Diagnose (5 min)

```bash
# "Let's watch the agent's logs in real-time"
kubectl logs -f deployment/aiops-agent -n dev
```

**Expected output (what audience sees):**
```
2026-07-24 03:02:15 | INFO  | 🚨 INCIDENT DETECTED
2026-07-24 03:02:15 | INFO  | Pod: auth-service-7d9f8c-xk2pv
2026-07-24 03:02:15 | INFO  | Reason: ImagePullBackOff
2026-07-24 03:02:15 | INFO  | Namespace: dev
2026-07-24 03:02:16 | INFO  | 📋 Gathering context...
2026-07-24 03:02:16 | INFO  | - Pod events: 3 events collected
2026-07-24 03:02:16 | INFO  | - Pod logs: (no logs - container not running)
2026-07-24 03:02:16 | INFO  | - Deployment: auth-service, replicas: 1
2026-07-24 03:02:17 | INFO  | 🧠 Calling AWS Bedrock (Claude Haiku)...
2026-07-24 03:02:18 | INFO  | ─── BEDROCK RESPONSE ───
2026-07-24 03:02:18 | INFO  | Root Cause: ImagePullBackOff — image 'nginx:doesnotexist' does not exist in registry
2026-07-24 03:02:18 | INFO  | Action: ALERT (image issue cannot be auto-fixed)
2026-07-24 03:02:18 | INFO  | Confidence: HIGH
2026-07-24 03:02:18 | INFO  | Suggestion: Rollback to previous known-good image tag
2026-07-24 03:02:18 | INFO  | ─────────────────────────
2026-07-24 03:02:18 | INFO  | 📢 Action: ALERT (not auto-fixable)
2026-07-24 03:02:18 | INFO  | ✅ Incident logged. MTTR tracking started.
```

**Say:** "Look — the agent detected it in 30 seconds. It gathered context, called Bedrock, and Bedrock correctly identified that this is an image issue — it can't be auto-fixed by restarting. Smart enough to know when NOT to act."

### Step 4: Demo a Fixable Scenario (5 min)

```bash
# Fix the image first
kubectl set image deployment/auth-service auth-service=nginx:latest -n dev

# Wait for it to be healthy, then simulate OOMKill or CrashLoop
kubectl exec deployment/auth-service -n dev -- kill 1
```

**Expected agent output:**
```
2026-07-24 03:05:30 | INFO  | 🚨 INCIDENT DETECTED
2026-07-24 03:05:30 | INFO  | Pod: auth-service-abc123
2026-07-24 03:05:30 | INFO  | Reason: CrashLoopBackOff (restart count: 3)
2026-07-24 03:05:31 | INFO  | 📋 Gathering context...
2026-07-24 03:05:32 | INFO  | 🧠 Calling AWS Bedrock...
2026-07-24 03:05:33 | INFO  | Root Cause: Process killed — likely transient failure
2026-07-24 03:05:33 | INFO  | Action: RESTART
2026-07-24 03:05:33 | INFO  | Confidence: HIGH
2026-07-24 03:05:33 | INFO  | 🔧 Executing: DELETE pod auth-service-abc123
2026-07-24 03:05:34 | INFO  | ⏳ Waiting 60s for verification...
2026-07-24 03:06:34 | INFO  | ✅ Pod auth-service-def456 is HEALTHY (1/1 Ready)
2026-07-24 03:06:34 | INFO  | 📊 MTTR: 64 seconds
```

**Say:** "64 seconds. From crash to healthy. No human involved. At 3 AM, you'd still be sleeping. THAT is AIOps."

### Step 5: Wrap Up (2 min)

```bash
# Show everything is healthy again
kubectl get pods -n dev

# Show the metrics
curl http://localhost:8000/metrics | grep aiops
# aiops_incidents_total{namespace="dev",service="auth-service",reason="CrashLoopBackOff"} 1
# aiops_mttr_seconds_bucket{namespace="dev",service="auth-service",le="120"} 1
```

**Say:** "Everything we built today — K8s API, IRSA, Bedrock, Python — all production patterns. This is what gets you hired as an AI DevOps engineer in 2026."

---

## Delivery Tips

| Do | Don't |
|---|---|
| Show real terminal output | Use slides with screenshots |
| Break things live (risky but impressive) | Pre-record the demo |
| Explain the "why" behind each step | Just show commands without context |
| Compare: "manually this takes 30 min" | Assume audience knows what IRSA is |
| Show the Bedrock response (it's the wow moment) | Skip error handling / guardrails |

## Backup Plan (If Demo Fails)

If Bedrock or the cluster has issues during live demo:
1. Have a pre-recorded terminal session (use `asciinema`)
2. Show the agent logs from a previous successful run (save them)
3. Walk through the code instead: "Here's what WOULD happen..."

---

## Audience Questions to Prepare For

| Question | Answer |
|---|---|
| "How much does Bedrock cost?" | ~$0.01 per incident. 100 incidents/month = $1. |
| "What if the agent breaks something?" | Guardrails: dev=auto, prod=alert-only. Max 1 retry. |
| "Why not just use PagerDuty?" | PagerDuty wakes YOU up. This fixes it BEFORE you wake up. |
| "Can this replace an SRE?" | No. It handles known patterns. Novel failures still need humans. |
| "Why Bedrock and not OpenAI?" | Data stays in your AWS account. No external API calls. Compliance. |
| "How is this different from K8s self-healing (restart policy)?" | K8s restarts blindly. This UNDERSTANDS why it crashed and chooses the right action. |
