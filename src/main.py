"""
Zen Pharma AIOps Self-Healing Agent
Watches K8s pods → Detects failures → Calls Bedrock → Auto-heals
"""

import time
import json
import logging
import os
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

from kubernetes import client, config
import boto3

# ─── Config ──────────────────────────────────────────────────────────────────

NAMESPACE = os.getenv("WATCH_NAMESPACE", "prod")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-east-1")
BEDROCK_MODEL = os.getenv("BEDROCK_MODEL", "amazon.nova-pro-v1:0")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "30"))

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("aiops")

# ─── K8s Client ──────────────────────────────────────────────────────────────

try:
    config.load_incluster_config()
    log.info("Loaded in-cluster K8s config")
except config.ConfigException:
    config.load_kube_config()
    log.info("Loaded local kubeconfig")

v1 = client.CoreV1Api()
apps_v1 = client.AppsV1Api()

# ─── Bedrock Client ──────────────────────────────────────────────────────────

bedrock = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)

# ─── Cooldown tracking ───────────────────────────────────────────────────────

recent_incidents = {}


def is_on_cooldown(pod_name):
    last = recent_incidents.get(pod_name, 0)
    return (time.time() - last) < 300


def mark_incident(pod_name):
    recent_incidents[pod_name] = time.time()


# ─── Gather Context ──────────────────────────────────────────────────────────

def get_pod_logs(pod_name, namespace):
    try:
        return v1.read_namespaced_pod_log(
            name=pod_name, namespace=namespace, tail_lines=50, previous=True
        )
    except Exception:
        pass
    try:
        return v1.read_namespaced_pod_log(
            name=pod_name, namespace=namespace, tail_lines=50
        )
    except Exception as e:
        return f"No logs available: {e}"


def get_pod_events(pod_name, namespace):
    events = v1.list_namespaced_event(
        namespace=namespace,
        field_selector=f"involvedObject.name={pod_name}",
    )
    lines = []
    for e in events.items[-10:]:
        lines.append(f"{e.last_timestamp} | {e.reason} | {e.message}")
    return "\n".join(lines) if lines else "No events found"


def get_pod_info(pod_name, namespace):
    pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
    restart_count = 0
    container_state = "Unknown"
    for cs in pod.status.container_statuses or []:
        restart_count = cs.restart_count
        if cs.state.waiting:
            container_state = cs.state.waiting.reason
        elif cs.state.running:
            container_state = "Running"
        elif cs.state.terminated:
            container_state = cs.state.terminated.reason
    return {
        "phase": pod.status.phase,
        "container_state": container_state,
        "restart_count": restart_count,
        "image": pod.spec.containers[0].image if pod.spec.containers else "unknown",
    }


def get_deployment_for_pod(pod_name, namespace):
    """Find the deployment that owns this pod."""
    pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
    for ref in pod.metadata.owner_references or []:
        if ref.kind == "ReplicaSet":
            rs = apps_v1.read_namespaced_replica_set(name=ref.name, namespace=namespace)
            for rs_ref in rs.metadata.owner_references or []:
                if rs_ref.kind == "Deployment":
                    return rs_ref.name
    return None


def get_deployment_history(deploy_name, namespace):
    """Get current and previous WORKING image from deployment."""
    deploy = apps_v1.read_namespaced_deployment(name=deploy_name, namespace=namespace)
    current_image = deploy.spec.template.spec.containers[0].image

    # Get replicasets — only consider ones that had ready replicas (actually worked)
    rs_list = apps_v1.list_namespaced_replica_set(
        namespace=namespace,
        label_selector=f"app={deploy_name}"
    )
    good_images = set()
    for rs in rs_list.items:
        if rs.spec.template.spec.containers:
            img = rs.spec.template.spec.containers[0].image
            # Only include if this RS had pods that were actually ready at some point
            if (rs.status.ready_replicas and rs.status.ready_replicas > 0) or \
               (rs.status.replicas and rs.status.replicas > 0 and rs.status.available_replicas and rs.status.available_replicas > 0):
                if img != current_image:
                    good_images.add(img)

    # If no good images found from RS status, use the image from the YAML spec
    # (the original deployment image before any kubectl set image)
    if not good_images:
        good_images.add("nginx:1.25-alpine")  # known-good default for pharma-web

    return current_image, list(good_images)


# ─── Bedrock Analysis ────────────────────────────────────────────────────────

def call_bedrock(pod_name, namespace, events_text, logs_text, pod_info, deploy_name, current_image, previous_images):
    """Send context to Bedrock for root cause analysis and get fix command."""
    prompt = f"""You are a Kubernetes SRE automation agent. A pod is failing and you MUST fix it automatically. No human intervention.

POD: {pod_name}
DEPLOYMENT: {deploy_name}
NAMESPACE: {namespace}
STATUS: {pod_info['phase']} / {pod_info['container_state']}
RESTART COUNT: {pod_info['restart_count']}
CURRENT IMAGE: {current_image}
PREVIOUS KNOWN-GOOD IMAGES: {previous_images}

EVENTS:
{events_text}

LOGS:
{logs_text[:2000]}

You MUST choose ONE action to fix this. Available actions:

1. ROLLBACK - Roll back to a previous known-good image. Use when: ImagePullBackOff, ErrImagePull, bad image tag.
2. RESTART - Delete the pod so Deployment recreates it. Use when: CrashLoopBackOff, OOMKilled, transient errors.
3. SCALE - Scale deployment to 0 then back to desired replicas. Use when: stuck containers, CreateContainerConfigError.

Respond ONLY in this exact JSON format:
{{"action": "ROLLBACK or RESTART or SCALE", "root_cause": "one sentence explanation", "fix_details": "what exactly you are doing to fix it", "rollback_image": "image:tag (only if action is ROLLBACK, use one from PREVIOUS KNOWN-GOOD IMAGES)"}}"""

    # Use converse API — works with all Bedrock models (Nova, Claude, etc.)
    response = bedrock.converse(
        modelId=BEDROCK_MODEL,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 400}
    )
    text = response["output"]["message"]["content"][0]["text"]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return {"action": "RESTART", "root_cause": "Could not parse response, defaulting to restart", "fix_details": "Deleting pod"}


# ─── Execute Remediation ─────────────────────────────────────────────────────

def execute_fix(analysis, pod_name, deploy_name, namespace):
    """Execute the fix — NO human intervention, just fix it."""
    action = analysis.get("action", "RESTART")

    if action == "ROLLBACK":
        rollback_image = analysis.get("rollback_image", "")
        if rollback_image:
            log.info(f"  🔧 ROLLING BACK: Setting image to {rollback_image}")
            body = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [{"name": deploy_name.split("-")[0] if "-" in deploy_name else "nginx", "image": rollback_image}]
                        }
                    }
                }
            }
            # Use strategic merge patch
            apps_v1.patch_namespaced_deployment(
                name=deploy_name, namespace=namespace,
                body=body
            )
            return "ROLLED_BACK"
        else:
            # Fallback: restart
            log.info(f"  🔧 No rollback image found, restarting pod instead")
            v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
            return "RESTARTED"

    elif action == "RESTART":
        log.info(f"  🔧 RESTARTING: Deleting pod {pod_name}")
        v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
        return "RESTARTED"

    elif action == "SCALE":
        log.info(f"  🔧 SCALING: Cycling deployment {deploy_name}")
        # Scale to 0
        apps_v1.patch_namespaced_deployment_scale(
            name=deploy_name, namespace=namespace,
            body={"spec": {"replicas": 0}}
        )
        time.sleep(5)
        # Scale back to 2
        apps_v1.patch_namespaced_deployment_scale(
            name=deploy_name, namespace=namespace,
            body={"spec": {"replicas": 2}}
        )
        return "SCALED"

    else:
        log.info(f"  🔧 Unknown action '{action}', defaulting to restart")
        v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
        return "RESTARTED"


# ─── Verify ──────────────────────────────────────────────────────────────────

def verify_health(deploy_name, namespace):
    """Wait and check if pods recovered."""
    log.info(f"  ⏳ Verifying health in 45 seconds...")
    time.sleep(45)
    try:
        deploy = apps_v1.read_namespaced_deployment(name=deploy_name, namespace=namespace)
        ready = deploy.status.ready_replicas or 0
        desired = deploy.spec.replicas or 1
        if ready >= desired:
            log.info(f"  ✅ HEALED! {ready}/{desired} pods ready")
            return True
        else:
            log.warning(f"  ⚠️  Partially healed: {ready}/{desired} pods ready")
            return False
    except Exception as e:
        log.error(f"  ❌ Verification error: {e}")
        return False


# ─── Main Watch Loop ─────────────────────────────────────────────────────────

def watch_pods():
    log.info("=" * 60)
    log.info("  ZEN PHARMA AIOps SELF-HEALING AGENT")
    log.info("=" * 60)
    log.info(f"  Watching namespace: {NAMESPACE}")
    log.info(f"  Bedrock model:      {BEDROCK_MODEL}")
    log.info(f"  Mode:               FULL AUTO-HEAL (no human needed)")
    log.info(f"  Check interval:     {CHECK_INTERVAL}s")
    log.info("=" * 60)
    log.info("")

    while True:
        try:
            pods = v1.list_namespaced_pod(namespace=NAMESPACE)

            for pod in pods.items:
                pod_name = pod.metadata.name
                if "aiops-agent" in pod_name:
                    continue

                for cs in pod.status.container_statuses or []:
                    is_failing = False
                    reason = ""

                    if cs.state.waiting and cs.state.waiting.reason in [
                        "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull",
                        "CreateContainerConfigError"
                    ]:
                        is_failing = True
                        reason = cs.state.waiting.reason
                    elif cs.state.terminated and cs.state.terminated.reason == "OOMKilled":
                        is_failing = True
                        reason = "OOMKilled"
                    elif cs.restart_count >= 3 and not cs.ready:
                        is_failing = True
                        reason = f"CrashLoop (restarts={cs.restart_count})"

                    if is_failing and not is_on_cooldown(pod_name):
                        mark_incident(pod_name)
                        log.info("─" * 60)
                        log.info(f"  🚨 INCIDENT DETECTED")
                        log.info(f"  Pod:       {pod_name}")
                        log.info(f"  Reason:    {reason}")
                        log.info(f"  Namespace: {NAMESPACE}")
                        log.info("─" * 60)

                        # Gather context
                        log.info(f"  📋 Gathering context...")
                        events_text = get_pod_events(pod_name, NAMESPACE)
                        logs_text = get_pod_logs(pod_name, NAMESPACE)
                        pod_info = get_pod_info(pod_name, NAMESPACE)

                        # Find deployment
                        deploy_name = get_deployment_for_pod(pod_name, NAMESPACE)
                        if not deploy_name:
                            deploy_name = pod.metadata.labels.get("app", "unknown")

                        # Get image history
                        current_image, previous_images = get_deployment_history(deploy_name, NAMESPACE)
                        log.info(f"  - Deployment:    {deploy_name}")
                        log.info(f"  - Current image: {current_image}")
                        log.info(f"  - Previous good: {previous_images}")
                        log.info(f"  - Status:        {pod_info['container_state']}")
                        log.info(f"  - Restarts:      {pod_info['restart_count']}")
                        log.info("")

                        # Call Bedrock
                        log.info(f"  🧠 Calling AWS Bedrock ({BEDROCK_MODEL})...")
                        try:
                            analysis = call_bedrock(
                                pod_name, NAMESPACE, events_text, logs_text,
                                pod_info, deploy_name, current_image, previous_images
                            )
                            log.info(f"  ┌─── BEDROCK ANALYSIS ───────────────────────")
                            log.info(f"  │ Root Cause:  {analysis.get('root_cause', 'unknown')}")
                            log.info(f"  │ Action:      {analysis.get('action', 'RESTART')}")
                            log.info(f"  │ Fix:         {analysis.get('fix_details', '')}")
                            if analysis.get("rollback_image"):
                                log.info(f"  │ Rollback to: {analysis.get('rollback_image')}")
                            log.info(f"  └─────────────────────────────────────────────")
                            log.info("")

                        except Exception as e:
                            log.error(f"  ❌ Bedrock failed: {e}")
                            log.info(f"  🔄 Falling back to default: RESTART")
                            analysis = {"action": "RESTART", "root_cause": str(e), "fix_details": "Bedrock unavailable, restarting pod"}

                        # Execute fix
                        log.info(f"  🔧 EXECUTING FIX...")
                        result = execute_fix(analysis, pod_name, deploy_name, NAMESPACE)
                        log.info(f"  → Result: {result}")
                        log.info("")

                        # Verify
                        healed = verify_health(deploy_name, NAMESPACE)

                        if healed:
                            log.info(f"  🎉 INCIDENT RESOLVED AUTOMATICALLY")
                        else:
                            log.info(f"  ⚠️  Fix applied but health check pending")

                        log.info("─" * 60)
                        log.info("")

        except Exception as e:
            log.error(f"Watch loop error: {e}")

        time.sleep(CHECK_INTERVAL)


# ─── Health Endpoint ─────────────────────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "healthy", "agent": "aiops", "model": BEDROCK_MODEL}).encode())

    def log_message(self, format, *args):
        pass


def start_health_server():
    HTTPServer(("0.0.0.0", 8000), HealthHandler).serve_forever()


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    Thread(target=start_health_server, daemon=True).start()
    log.info("Health endpoint on :8000")
    watch_pods()
