# Step 2: Deploy Sample Application

## What We're Deploying

A simple nginx-based web app (`pharma-web`) in the `prod` namespace. This gives us:
- A visible UI to show in the browser
- Something for the AIOps agent to monitor
- Easy to break (change image, kill pod) for demo purposes

---

## Deploy

```bash
kubectl apply -f k8s/sample-app.yaml
```

## Verify

```bash
# Check pods are running
kubectl get pods -n prod

# Expected:
# NAME                          READY   STATUS    RESTARTS   AGE
# pharma-web-5c49f86d85-jwv88   1/1     Running   0          24s
# pharma-web-5c49f86d85-wwzrt   1/1     Running   0          24s
```

---

## Access in Browser

**Node Public IP:** `54.242.60.17`  
**NodePort:** `30080`  
**URL:** `http://54.242.60.17:30080`

### How to find Node IP (if it changes):
```bash
kubectl get nodes -o wide
# Look at EXTERNAL-IP column
```

---

## Security Group

Node security group `sg-05f8cb2af7b364807` has been updated to allow inbound TCP port 30080 from 0.0.0.0/0.

```bash
# This was already done:
aws ec2 authorize-security-group-ingress \
  --group-id sg-05f8cb2af7b364807 \
  --protocol tcp --port 30080 \
  --cidr 0.0.0.0/0 \
  --region us-east-1
```

---

## What the App Contains

- **Deployment:** 2 replicas of `nginx:1.25-alpine`
- **ConfigMap:** Custom HTML page (Zen Pharma branded)
- **Service:** NodePort on 30080
- **Probes:** Liveness + Readiness on `/` port 80
- **Resources:** 50m CPU, 64Mi memory (lightweight)

---

## How to Break It (for Demo)

```bash
# Scenario 1: Bad image (ImagePullBackOff)
kubectl set image deployment/pharma-web nginx=nginx:doesnotexist -n prod

# Scenario 2: Kill the process (CrashLoopBackOff)
kubectl exec deployment/pharma-web -n prod -- kill 1

# Scenario 3: OOMKill (set tiny memory limit)
kubectl set resources deployment/pharma-web -c nginx --limits=memory=1Mi -n prod
```

## How to Fix It (manually, before agent is ready)

```bash
# Restore good image
kubectl set image deployment/pharma-web nginx=nginx:1.25-alpine -n prod

# Or delete and reapply
kubectl delete -f k8s/sample-app.yaml
kubectl apply -f k8s/sample-app.yaml
```

---

---

## Verified Outputs ✅

| Item | Value |
|---|---|
| Pods | 2/2 Running (`pharma-web-5c49f86d85-jwv88`, `pharma-web-5c49f86d85-wwzrt`) |
| Service | `pharma-web` — NodePort 30080 |
| Security Group | `sg-05f8cb2af7b364807` — Port 30080 open to 0.0.0.0/0 |
| SG Rule ID | `sgr-08bff1bbbd021fbff` |
| Node 1 Public IP | `54.242.60.17` (ip-192-168-2-213.ec2.internal) |
| Node 2 Public IP | (check with `kubectl get nodes -o wide`) |
| App URL | **http://54.242.60.17:30080** |
| Namespace | `prod` |
| Image | `nginx:1.25-alpine` |
| Replicas | 2 |
| Liveness Probe | `GET /` port 80, every 10s |
| Readiness Probe | `GET /` port 80, every 5s |

---

## Next Step

→ [03-create-irsa-role.md](./03-create-irsa-role.md) — Create IRSA role so the agent can call Bedrock.
