# AIOps Self-Healing Agent — Live Demo Testing Guide

> **App URL:** http://54.242.60.17:30080  
> **Cluster:** aiops (us-east-1)  
> **Namespace:** prod  
> **Agent Model:** Amazon Nova Pro  
> **Repo:** https://github.com/ajay-bj/zen-aiops-agent

---

## Pre-Demo Setup

### Terminal 1 — Agent Logs (keep open entire demo)

```bash
kubectl logs -f deployment/aiops-agent -n prod
```

### Terminal 2 — Run commands to break/fix

```bash
# Verify everything is healthy first
kubectl get pods -n prod
```

### Browser

```
http://54.242.60.17:30080
```

Verify page loads with "Zen Pharma Platform — Service Healthy"

---

## Demo 1: OOMKilled (Memory Exhaustion)

### Terminal 2 — Break it:

```bash
kubectl set resources deployment/pharma-web -n prod -c nginx --limits=memory=4Mi --requests=memory=2Mi
```

### Browser — Verify it's DOWN:

```
http://54.242.60.17:30080
```

Refresh — page should be DOWN ❌

### Terminal 1 — Watch agent detect and fix:

Agent will show:
```
🚨 INCIDENT DETECTED
Pod: pharma-web-xxx
Reason: OOMKilled
🧠 Calling AWS Bedrock...
Action: RESTART
🔧 RESTARTING: Deleting pod
✅ HEALED!
🎉 INCIDENT RESOLVED AUTOMATICALLY
```

### Browser — Verify it's BACK UP:

```
http://54.242.60.17:30080
```

Refresh — page should be UP ✅

### Terminal 2 — Reset for next demo:

```bash
kubectl apply -f k8s/sample-app.yaml
```

Wait 30 seconds:

```bash
kubectl get pods -n prod
```

Verify: `pharma-web 1/1 Running`

---

## Demo 2: ImagePullBackOff (Bad Deployment — Intelligent Rollback)

### Terminal 2 — Break it:

```bash
kubectl set image deployment/pharma-web nginx=nginx:v99-does-not-exist -n prod
```

### Browser — Verify it's DOWN:

```
http://54.242.60.17:30080
```

Refresh — page should be DOWN ❌

### Terminal 1 — Watch agent detect and ROLLBACK:

Agent will show:
```
🚨 INCIDENT DETECTED
Pod: pharma-web-xxx
Reason: ImagePullBackOff
📋 Gathering context...
- Current image: nginx:v99-does-not-exist
- Previous good: ['nginx:1.25-alpine']
🧠 Calling AWS Bedrock...
Root Cause: Failed to pull image — tag does not exist
Action: ROLLBACK
Rollback to: nginx:1.25-alpine
🔧 ROLLING BACK: Setting image to nginx:1.25-alpine
✅ HEALED!
🎉 INCIDENT RESOLVED AUTOMATICALLY
```

### Browser — Verify it's BACK UP:

```
http://54.242.60.17:30080
```

Refresh — page should be UP ✅

### Terminal 2 — Reset for next demo:

```bash
kubectl apply -f k8s/sample-app.yaml
```

Wait 30 seconds:

```bash
kubectl get pods -n prod
```

---

## Demo 3: CrashLoopBackOff (Process Crash)

### Terminal 2 — Break it (run 3 times quickly):

```bash
kubectl exec deployment/pharma-web -n prod -- kill 1
```

```bash
kubectl exec deployment/pharma-web -n prod -- kill 1
```

```bash
kubectl exec deployment/pharma-web -n prod -- kill 1
```

### Browser — Verify it's DOWN:

```
http://54.242.60.17:30080
```

Refresh — page should be DOWN ❌ (or slow)

### Terminal 1 — Watch agent detect and fix:

Agent will show:
```
🚨 INCIDENT DETECTED
Pod: pharma-web-xxx
Reason: CrashLoop (restarts=3)
🧠 Calling AWS Bedrock...
Root Cause: Process terminated unexpectedly
Action: RESTART
🔧 RESTARTING: Deleting pod
✅ HEALED!
🎉 INCIDENT RESOLVED AUTOMATICALLY
```

### Browser — Verify it's BACK UP:

```
http://54.242.60.17:30080
```

Refresh — page should be UP ✅

### Terminal 2 — Reset:

```bash
kubectl apply -f k8s/sample-app.yaml
```

---

## Quick Reference — All Commands

### Check status:

```bash
kubectl get pods -n prod
```

### Watch agent logs (streaming):

```bash
kubectl logs -f deployment/aiops-agent -n prod
```

### Check agent logs (last 30 lines):

```bash
kubectl logs deployment/aiops-agent -n prod --tail=30
```

### Full reset (if things go wrong):

```bash
kubectl apply -f k8s/sample-app.yaml
kubectl rollout restart deployment/aiops-agent -n prod
```

### Check app in browser:

```
http://54.242.60.17:30080
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Agent not detecting | `kubectl get pods -n prod` — is agent Running? |
| Agent crashed | `kubectl rollout restart deployment/aiops-agent -n prod` |
| pharma-web stuck in bad state | `kubectl delete deployment pharma-web -n prod` then `kubectl apply -f k8s/sample-app.yaml` |
| Browser shows old page | Hard refresh: Ctrl+Shift+R |
| Multiple old pods showing | `kubectl delete replicaset --all -n prod` then reapply |
| Node IP changed | `kubectl get nodes -o wide` → check EXTERNAL-IP column |
