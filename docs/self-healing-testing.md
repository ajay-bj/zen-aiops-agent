# AIOps Self-Healing Agent — Live Demo Guide

> **Duration:** 15-20 minutes  
> **Prerequisites:** Cluster running, agent deployed, pharma-web healthy  
> **App URL:** http://54.242.60.17:30080  
> **Setup:** Two terminals side by side + browser open

---

## Pre-Demo Checklist

```bash
# Verify everything is healthy
kubectl get pods -n prod
# Expected:
# aiops-agent-xxx   1/1   Running   0   Xm
# pharma-web-xxx    1/1   Running   0   Xm

# Verify app is accessible in browser
# Open: http://54.242.60.17:30080

# Start watching agent logs (KEEP THIS OPEN throughout the demo)
kubectl logs -f deployment/aiops-agent -n prod
```

---

## Demo 1: OOMKilled (Memory Exhaustion)

**Story:** "A developer deployed a service with a memory leak. The container keeps exceeding its memory limit and getting killed by the OS."

### Break it:

```bash
# Set an impossibly low memory limit (4Mi — nginx needs at least 20Mi)
kubectl set resources deployment/pharma-web -n prod -c nginx --limits=memory=4Mi --requests=memory=2Mi
```

### What audience sees:

**Browser:** Refresh http://54.242.60.17:30080 → **PAGE DOWN** ❌

**Agent logs (Terminal 1):**
```
────────────────────────────────────────────────────────────
  🚨 INCIDENT DETECTED
  Pod:       pharma-web-xxx
  Reason:    OOMKilled
  Namespace: prod
────────────────────────────────────────────────────────────
  📋 Gathering context...
  - Deployment:    pharma-web
  - Current image: nginx:1.25-alpine
  - Status:        OOMKilled
  - Restarts:      3

  🧠 Calling AWS Bedrock (amazon.nova-pro-v1:0)...
  ┌─── BEDROCK ANALYSIS ───────────────────────
  │ Root Cause:  Container exceeded memory limit of 4Mi
  │ Action:      RESTART
  │ Fix:         Restarting pod to recover from transient OOM
  └─────────────────────────────────────────────

  🔧 EXECUTING FIX...
  🔧 RESTARTING: Deleting pod pharma-web-xxx
  → Result: RESTARTED

  ⏳ Verifying health in 45 seconds...
  ✅ HEALED! 1/1 pods ready
  🎉 INCIDENT RESOLVED AUTOMATICALLY
────────────────────────────────────────────────────────────
```

### What you say:
> "The AI detected OOMKilled, understood it's a memory issue, and restarted the pod. In a real scenario with persistent OOM, it would escalate or recommend increasing memory limits."

### Restore for next demo:

```bash
# Reset memory back to normal
kubectl apply -f k8s/sample-app.yaml
# Wait 30 seconds for pod to stabilize
```

### Verify:
**Browser:** Refresh → **PAGE BACK UP** ✅

---

## Demo 2: ImagePullBackOff (Bad Deployment)

**Story:** "Someone pushed a wrong image tag in the CI pipeline. The pod can't pull the image. This is the most impressive demo — the agent ROLLS BACK to the previous working image."

### Break it:

```bash
# Push a bad image tag (simulates wrong CI deploy)
kubectl set image deployment/pharma-web nginx=nginx:v99-does-not-exist -n prod
```

### What audience sees:

**Browser:** Refresh http://54.242.60.17:30080 → **PAGE DOWN** ❌

**Agent logs (Terminal 1):**
```
────────────────────────────────────────────────────────────
  🚨 INCIDENT DETECTED
  Pod:       pharma-web-xxx
  Reason:    ImagePullBackOff
  Namespace: prod
────────────────────────────────────────────────────────────
  📋 Gathering context...
  - Deployment:    pharma-web
  - Current image: nginx:v99-does-not-exist
  - Previous good: ['nginx:1.25-alpine']
  - Status:        ImagePullBackOff
  - Restarts:      0

  🧠 Calling AWS Bedrock (amazon.nova-pro-v1:0)...
  ┌─── BEDROCK ANALYSIS ───────────────────────
  │ Root Cause:  Failed to pull image — tag does not exist in registry
  │ Action:      ROLLBACK
  │ Fix:         Rolling back to previous known-good image
  │ Rollback to: nginx:1.25-alpine
  └─────────────────────────────────────────────

  🔧 EXECUTING FIX...
  🔧 ROLLING BACK: Setting image to nginx:1.25-alpine
  → Result: ROLLED_BACK

  ⏳ Verifying health in 45 seconds...
  ✅ HEALED! 1/1 pods ready
  🎉 INCIDENT RESOLVED AUTOMATICALLY
────────────────────────────────────────────────────────────
```

### What you say:
> "This is the WOW moment. The AI didn't just restart — it analyzed the problem, understood it's a bad image, looked at the deployment history, found the last working image, and rolled back AUTOMATICALLY. No human. No PagerDuty. No 3 AM wake-up."

### Verify:
**Browser:** Refresh → **PAGE BACK UP** ✅

---

## Demo 3: CrashLoopBackOff (Process Crash)

**Story:** "The application process crashed unexpectedly — maybe a segfault, an unhandled exception, or a dependency failure. The pod keeps restarting and failing."

### Break it:

```bash
# Kill the nginx process inside the container
kubectl exec deployment/pharma-web -n prod -- kill 1
```

Note: You may need to run this 2-3 times quickly (K8s restarts fast):
```bash
kubectl exec deployment/pharma-web -n prod -- kill 1
kubectl exec deployment/pharma-web -n prod -- kill 1
kubectl exec deployment/pharma-web -n prod -- kill 1
```

### What audience sees:

**Browser:** Refresh http://54.242.60.17:30080 → **PAGE DOWN** ❌ (briefly)

**Agent logs (Terminal 1):**
```
────────────────────────────────────────────────────────────
  🚨 INCIDENT DETECTED
  Pod:       pharma-web-xxx
  Reason:    CrashLoop (restarts=3)
  Namespace: prod
────────────────────────────────────────────────────────────
  📋 Gathering context...
  - Deployment:    pharma-web
  - Current image: nginx:1.25-alpine
  - Status:        CrashLoopBackOff
  - Restarts:      3

  🧠 Calling AWS Bedrock (amazon.nova-pro-v1:0)...
  ┌─── BEDROCK ANALYSIS ───────────────────────
  │ Root Cause:  Process terminated unexpectedly — transient failure
  │ Action:      RESTART
  │ Fix:         Deleting pod to get a fresh start
  └─────────────────────────────────────────────

  🔧 EXECUTING FIX...
  🔧 RESTARTING: Deleting pod pharma-web-xxx
  → Result: RESTARTED

  ⏳ Verifying health in 45 seconds...
  ✅ HEALED! 1/1 pods ready
  🎉 INCIDENT RESOLVED AUTOMATICALLY
────────────────────────────────────────────────────────────
```

### What you say:
> "In production, CrashLoopBackOff is the #1 alert that wakes engineers at 3 AM. Our agent detected it, read the logs, identified it as a transient crash, and restarted the pod — all in under 90 seconds. The on-call engineer sleeps through the night."

### Verify:
**Browser:** Refresh → **PAGE BACK UP** ✅

---

## Closing Statement (After All 3 Demos)

> "You just saw an AI agent handle 3 different production failure scenarios:
> 1. Memory exhaustion — detected and restarted
> 2. Bad deployment — intelligently rolled back to the last working version  
> 3. Process crash — detected the crash loop and recovered
>
> Total code: ONE Python file. No extra infrastructure. Just a pod with IRSA talking to Bedrock.
>
> In a real organization, you'd add Slack alerts, JIRA ticket creation, runbook integration, and escalation chains. But the core pattern — watch, think, act — is what you just saw."

---

## Troubleshooting (If Things Go Wrong During Demo)

| Problem | Quick Fix |
|---|---|
| Agent not detecting | Check: `kubectl get pods -n prod` — is agent running? |
| Bedrock error | Agent falls back to RESTART anyway (still heals) |
| Page still down after fix | Wait 30 sec, hard refresh (Ctrl+Shift+R) |
| Too many old pods | `kubectl delete pods --all -n prod` then reapply |
| Reset everything | `kubectl apply -f k8s/sample-app.yaml` |
| Agent in CrashLoop | `kubectl rollout restart deployment/aiops-agent -n prod` |

---

## Quick Reset Between Demos

```bash
# Full reset to clean state
kubectl apply -f k8s/sample-app.yaml
# Wait 30 seconds
kubectl get pods -n prod
# Verify: 1/1 Running for pharma-web, 1/1 Running for aiops-agent
```

---

## Architecture Slide (Show Before Demo)

```
EKS Cluster (prod namespace)
┌────────────────────────────────────────────────┐
│                                                 │
│  aiops-agent pod ──watch──→ pharma-web pod      │
│       │                         │               │
│       │ K8s API                 │ nginx:80      │
│       │ (logs, events)          │               │
│       ▼                         ▼               │
│  AWS Bedrock ◄──IRSA──    Browser ◄──NodePort   │
│  (Nova Pro)            http://54.242.60.17:30080│
│       │                                         │
│       ▼                                         │
│  Decision: RESTART / ROLLBACK / SCALE           │
│       │                                         │
│       ▼                                         │
│  K8s API: delete pod / patch deployment         │
│       │                                         │
│       ▼                                         │
│  Verify: pod healthy? ✅                         │
└────────────────────────────────────────────────┘
```

---

## Key Numbers to Mention

- Agent check interval: 30 seconds
- Bedrock response time: ~1 second
- Health verification: 45 seconds
- Total MTTR: ~90 seconds (vs 15-30 minutes manual)
- Cost: ~$0.01 per incident (Nova Pro token cost)
- Code: 1 Python file (~200 lines)
