# Zen Pharma AIOps Self-Healing Agent

An AI-powered Kubernetes self-healing agent that monitors pods, detects failures, calls AWS Bedrock for root cause analysis, and automatically fixes issues — without human intervention.

## What It Does

```
Pod crashes → Agent detects (30s) → Reads logs → Calls Bedrock → Fixes it → Verifies health
```

The agent runs as a pod inside EKS and watches other pods for failures like CrashLoopBackOff, OOMKilled, and ImagePullBackOff. When it detects an issue, it gathers context (logs, events, deployment history), sends it to AWS Bedrock (Amazon Nova Pro) for analysis, and executes the recommended fix automatically.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  AWS EKS Cluster (prod namespace)                            │
│                                                              │
│  ┌─────────────────┐         ┌─────────────────┐            │
│  │  aiops-agent    │──watch─▶│  pharma-web     │◀── Browser │
│  │  (Python pod)   │◀─logs───│  (nginx pod)    │            │
│  │                 │──fix───▶│                 │            │
│  └────────┬────────┘         └─────────────────┘            │
│           │ IRSA (OIDC)                                      │
└───────────┼──────────────────────────────────────────────────┘
            ▼
   ┌─────────────────┐
   │  AWS Bedrock    │
   │  Nova Pro       │
   │  (AI Analysis)  │
   └─────────────────┘
```

## Tech Stack

| Component | Technology |
|---|---|
| Agent | Python 3.12 + kubernetes client + boto3 |
| AI Model | Amazon Nova Pro (via Bedrock Converse API) |
| Auth (AWS) | IRSA — no static keys, OIDC tokens |
| Auth (K8s) | RBAC — ClusterRole + ClusterRoleBinding |
| Cluster | AWS EKS 1.31 |
| CI/CD | GitHub Actions → ECR |
| Container | Docker (python:3.12-slim, non-root) |

## Failure Scenarios Handled

| Scenario | Detection | Agent Action |
|---|---|---|
| CrashLoopBackOff | Restart count ≥ 3 | RESTART pod |
| OOMKilled | Container terminated with OOM | RESTART pod |
| ImagePullBackOff | Bad image tag | ROLLBACK to previous good image |
| ErrImagePull | Image doesn't exist | ROLLBACK |
| CreateContainerConfigError | Missing config/secret | ALERT |

## Project Structure

```
zen-aiops-agent/
├── src/
│   ├── __init__.py
│   └── main.py                  # Agent code (watcher + bedrock + executor)
├── k8s/
│   ├── sample-app.yaml          # Demo app (pharma-web nginx)
│   ├── aiops-agent-deploy.yaml  # Agent deployment
│   ├── aiops-rbac.yaml          # ServiceAccount + ClusterRole + Binding
│   ├── trust-policy.json        # IRSA trust policy
│   └── bedrock-policy.json      # IAM policy for Bedrock access
├── docs/
│   ├── 01-cluster-setup.md      # EKS provisioning guide
│   ├── 02-deploy-sample-app.md  # Sample app deployment
│   ├── self-healing-testing.md  # Live demo guide (3 scenarios)
│   └── aiops-presentation-slides.md
├── .github/workflows/
│   └── build.yml                # CI: Build → Push to ECR
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Setup Guide — Complete Infrastructure Provisioning

### Step 1: Create EKS Cluster

```bash
# Install eksctl (Windows)
Invoke-WebRequest -Uri "https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_Windows_amd64.zip" -OutFile "$env:TEMP\eksctl.zip"
Expand-Archive -Path "$env:TEMP\eksctl.zip" -DestinationPath "$env:USERPROFILE\bin" -Force

# Create cluster with OIDC enabled
eksctl create cluster \
  --name aiops \
  --region us-east-1 \
  --version 1.31 \
  --nodegroup-name aiops-nodes \
  --node-type t3.medium \
  --nodes 2 \
  --nodes-min 1 \
  --nodes-max 3 \
  --managed \
  --with-oidc
```

**Output:**
```
Cluster: aiops
Region: us-east-1
Nodes: 2× t3.medium
OIDC: https://oidc.eks.us-east-1.amazonaws.com/id/<OIDC_ID>
```

### Step 2: Create Namespace

```bash
kubectl create namespace prod
```

### Step 3: Create ECR Repository

```bash
aws ecr create-repository \
  --repository-name aiops-agent \
  --region us-east-1
```

**Output:** `304312474711.dkr.ecr.us-east-1.amazonaws.com/aiops-agent`

### Step 4: Create IAM Policy (Bedrock Access)

```bash
aws iam create-policy \
  --policy-name aiops-agent-bedrock-policy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.*"
    }]
  }'
```

**Output:** `arn:aws:iam::304312474711:policy/aiops-agent-bedrock-policy`

### Step 5: Create IAM Role (IRSA Trust Policy)

```bash
# Get OIDC ID
aws eks describe-cluster --name aiops --region us-east-1 \
  --query "cluster.identity.oidc.issuer" --output text
# Output: https://oidc.eks.us-east-1.amazonaws.com/id/60357E7A0096F75A113D39DEB2A48EB3

# Create role with trust policy (k8s/trust-policy.json)
aws iam create-role \
  --role-name aiops-agent-role \
  --assume-role-policy-document file://k8s/trust-policy.json
```

**Trust policy** (`k8s/trust-policy.json`):
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::304312474711:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/60357E7A0096F75A113D39DEB2A48EB3"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "oidc.eks.us-east-1.amazonaws.com/id/60357E7A0096F75A113D39DEB2A48EB3:aud": "sts.amazonaws.com",
        "oidc.eks.us-east-1.amazonaws.com/id/60357E7A0096F75A113D39DEB2A48EB3:sub": "system:serviceaccount:prod:aiops-agent"
      }
    }
  }]
}
```

### Step 6: Attach Policy to Role

```bash
# Attach the Bedrock policy
aws iam attach-role-policy \
  --role-name aiops-agent-role \
  --policy-arn arn:aws:iam::304312474711:policy/aiops-agent-bedrock-policy

# Add inline policy for broader Bedrock access (inference profiles)
aws iam put-role-policy \
  --role-name aiops-agent-role \
  --policy-name bedrock-invoke-inline \
  --policy-document file://k8s/bedrock-policy.json
```

### Step 7: Create K8s RBAC + ServiceAccount

```bash
kubectl apply -f k8s/aiops-rbac.yaml
```

This creates:
- **ServiceAccount** `aiops-agent` in `prod` namespace (with IRSA annotation)
- **ClusterRole** `aiops-agent-role` (read pods/logs/events, delete pods, patch deployments)
- **ClusterRoleBinding** `aiops-agent-binding`

### Step 8: Deploy Sample Application

```bash
kubectl apply -f k8s/sample-app.yaml
```

Creates:
- Deployment: `pharma-web` (1 replica, nginx:1.25-alpine)
- ConfigMap: custom HTML page
- Service: NodePort 30080

### Step 9: Open Security Group for NodePort

```bash
# Find node security group
aws ec2 describe-instances --region us-east-1 \
  --filters "Name=tag:eks:cluster-name,Values=aiops" \
  --query "Reservations[0].Instances[0].SecurityGroups[*].GroupId" --output text

# Open port 30080
aws ec2 authorize-security-group-ingress \
  --group-id <SG_ID> \
  --protocol tcp --port 30080 --cidr 0.0.0.0/0 \
  --region us-east-1
```

### Step 10: Setup GitHub Actions (CI/CD)

```bash
# Create repo and push
gh repo create zen-aiops-agent --public --source=. --remote=origin --push

# Add AWS secrets for ECR push
gh secret set AWS_ACCESS_KEY_ID --body <your-key>
gh secret set AWS_SECRET_ACCESS_KEY --body <your-secret>
```

### Step 11: Deploy the Agent

```bash
# Wait for GitHub Actions to build and push image to ECR
# Then deploy:
kubectl apply -f k8s/aiops-agent-deploy.yaml
```

---

## Resource Summary

| Resource | Type | Name / ID |
|---|---|---|
| EKS Cluster | Compute | `aiops` (us-east-1, v1.31) |
| Node Group | Compute | `aiops-nodes` (2× t3.medium) |
| Namespace | K8s | `prod` |
| ECR Repo | Registry | `304312474711.dkr.ecr.us-east-1.amazonaws.com/aiops-agent` |
| IAM Policy | IAM | `aiops-agent-bedrock-policy` |
| IAM Role | IAM | `aiops-agent-role` |
| OIDC Provider | IAM | `60357E7A0096F75A113D39DEB2A48EB3` |
| ServiceAccount | K8s | `prod/aiops-agent` (IRSA annotated) |
| ClusterRole | K8s | `aiops-agent-role` |
| ClusterRoleBinding | K8s | `aiops-agent-binding` |
| Security Group Rule | EC2 | Port 30080 open (sgr-08bff1bbbd021fbff) |
| GitHub Repo | Code | `ajay-bj/zen-aiops-agent` |
| GitHub Secrets | CI | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |

---

## How to Test (Self-Healing Demos)

```bash
# Terminal 1: Watch agent logs
kubectl logs -f deployment/aiops-agent -n prod

# Terminal 2: Break things

# Demo 1 — OOMKilled
kubectl set resources deployment/pharma-web -n prod -c nginx --limits=memory=4Mi --requests=memory=2Mi

# Demo 2 — ImagePullBackOff
kubectl set image deployment/pharma-web nginx=nginx:v99-broken -n prod

# Demo 3 — CrashLoopBackOff
kubectl exec deployment/pharma-web -n prod -- kill 1

# Reset between demos
kubectl apply -f k8s/sample-app.yaml
```

---

## Cleanup (Delete Everything)

```bash
# Delete cluster (removes all K8s resources)
eksctl delete cluster --name aiops --region us-east-1

# Delete IAM resources
aws iam detach-role-policy --role-name aiops-agent-role --policy-arn arn:aws:iam::304312474711:policy/aiops-agent-bedrock-policy
aws iam delete-role-policy --role-name aiops-agent-role --policy-name bedrock-invoke-inline
aws iam delete-role --role-name aiops-agent-role
aws iam delete-policy --policy-arn arn:aws:iam::304312474711:policy/aiops-agent-bedrock-policy

# Delete ECR repo
aws ecr delete-repository --repository-name aiops-agent --region us-east-1 --force
```

---

## Cost

| Resource | Monthly Cost |
|---|---|
| EKS control plane | $73 (or ~$0.55 per 3-hour session) |
| 2× t3.medium nodes | $60 |
| Bedrock (Nova Pro) | ~$0.01 per incident |
| ECR | ~$0.10 |
| **Total (running 24/7)** | **~$133/month** |
| **Per demo session (3h)** | **~$0.55** |

**Tip:** Delete cluster after each session: `eksctl delete cluster --name aiops`
