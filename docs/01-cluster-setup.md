# Step 1: Provision EKS Cluster for AIOps Hands-On

## Prerequisites

- AWS CLI configured (`aws configure`)
- eksctl installed ([install guide](https://eksctl.io/installation/))
- kubectl installed
- AWS account with permissions to create EKS clusters

---

## Create the Cluster

```bash
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

**Time:** ~15-20 minutes

**What this creates:**
- EKS cluster named `aiops` in us-east-1
- Managed node group with 2× t3.medium instances (2 vCPU, 4GB each)
- VPC with public and private subnets
- OIDC provider (required for IRSA — how our agent will access Bedrock)
- IAM roles for cluster and node group
- Security groups for cluster communication

---

## Verify Cluster is Ready

```bash
# Check nodes are Ready
kubectl get nodes

# Expected output:
# NAME                             STATUS   ROLES    AGE   VERSION
# ip-192-168-xx-xx.ec2.internal    Ready    <none>   5m    v1.31.x
# ip-192-168-xx-xx.ec2.internal    Ready    <none>   5m    v1.31.x
```

```bash
# Check cluster info
kubectl cluster-info
```

```bash
# Confirm OIDC provider was created (needed for IRSA)
aws eks describe-cluster --name aiops --region us-east-1 \
  --query "cluster.identity.oidc.issuer" --output text

# Expected output (your ID will be different):
# https://oidc.eks.us-east-1.amazonaws.com/id/ABCDEF1234567890ABCDEF
```

```bash
# Verify OIDC is registered in IAM
aws iam list-open-id-connect-providers | grep $(aws eks describe-cluster \
  --name aiops --region us-east-1 \
  --query "cluster.identity.oidc.issuer" --output text | sed 's|https://||')
```

---

## Create Namespaces

```bash
kubectl create namespace prod
```

---

## Verify System Pods

```bash
kubectl get pods -n kube-system

# You should see: coredns, kube-proxy, aws-node running
```

---

## Cluster Details (Verified ✅)

| Value | Result |
|---|---|
| Cluster name | `aiops` |
| Region | `us-east-1` |
| Account ID | `304312474711` |
| K8s Version | `v1.31.14-eks-8f14419` |
| Nodes | 2× t3.medium (ip-192-168-2-213, ip-192-168-60-112) |
| OIDC Issuer URL | `https://oidc.eks.us-east-1.amazonaws.com/id/60357E7A0096F75A113D39DEB2A48EB3` |
| OIDC ID | `60357E7A0096F75A113D39DEB2A48EB3` |
| Namespaces created | `prod` |

**Commands to verify:**
```bash
aws eks describe-cluster --name aiops --region us-east-1 --query "cluster.status" --output text
# ACTIVE

kubectl get nodes
# 2 nodes Ready

aws eks describe-cluster --name aiops --region us-east-1 --query "cluster.identity.oidc.issuer" --output text
# https://oidc.eks.us-east-1.amazonaws.com/id/60357E7A0096F75A113D39DEB2A48EB3
```

You will need the OIDC ID (`60357E7A0096F75A113D39DEB2A48EB3`) in the next step when creating the IRSA role for the agent.

---

## Cost

| Resource | Cost |
|---|---|
| EKS control plane | $0.10/hour (~$73/month) |
| 2× t3.medium nodes | $0.0416/hour each (~$60/month total) |
| **Total if running 24/7** | **~$133/month** |
| **Per session (3 hours)** | **~$0.55** |

**Cost tip:** Delete the cluster after each session:
```bash
eksctl delete cluster --name aiops --region us-east-1
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `error: You must be logged in` | Run `aws eks update-kubeconfig --name aiops --region us-east-1` |
| Nodes stuck in `NotReady` | Wait 2-3 minutes, check `kubectl describe node` for events |
| OIDC provider not listed in IAM | Run `eksctl utils associate-iam-oidc-provider --cluster aiops --region us-east-1 --approve` |
| Timeout during creation | Check CloudFormation in AWS Console for stack errors |

---

## Next Step

→ [02-deploy-sample-service.md](./02-deploy-sample-service.md) — Deploy auth-service so the agent has something to monitor.
