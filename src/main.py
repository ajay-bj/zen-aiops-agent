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

from kubernetes import client, config, watch
import boto3

# ─── Config ──────────────────────────────────────────────────────────────────

NAMESPACE = os.getenv("WATCH_NAMESPACE", "prod")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-east-1")
BEDROCK_MODEL = os.getenv("BEDROCK_MODEL", "anthropic.claude-3-haiku-20240307")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "30"))
AUTO_HEAL = os.getenv("AUTO_HEAL", "true").lower() == "true"

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

recent_incidents = {}  # pod_name → timestamp (avoid re-acting within 5 min)


def is_on_cooldown(pod_name):
    last = recent_incidents.get(pod_name, 0)
    return (time.time() - last) < 300  # 5 min cooldown


def mark_incident(pod_name):
    recent_incidents[pod_name] = time.time()


# ─── Gather Context ──────────────────────────────────────────────────────────

def get_pod_logs(pod_name, namespace):
    """Read last 50 lines from pod (or previous container if crashing)."""
    try:
        logs = v1.read_namespaced_pod_log(
            name=pod_name, namespace=namespace, tail_lines=50, previous=True
        )
        return logs
    except Exception:
        pass
    try:
        logs = v1.read_namespaced_pod_log(
            name=pod_name, namespace=namespace, tail_lines=50
        )
        return logs
    except Exception as e:
        return f"Could not read logs: {e}"


def get_pod_events(pod_name, namespace):
    """Get K8s events for a specific pod."""
    events = v1.list_namespaced_event(
        namespace=namespace,
        field_selector=f"involvedObject.name={pod_name}",
    )
    lines = []
    for e in events.items[-10:]:  # last 10 events
        lines.append(f"{e.last_timestamp} | {e.reason} | {e.message}")
    return "\n".join(lines) if lines else "No events found"


def get_pod_info(pod_name, namespace):
    """Get pod status details."""
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


# ─── Bedrock Analysis ────────────────────────────────────────────────────────

def call_bedrock(pod_name, namespace, events_text, logs_text, pod_info):
    """Send context to Bedrock for root cause analysis."""
    prompt = f"""You are a Kubernetes SRE agent for a pharmaceutical platform on AWS EKS.

A pod is failing. Analyze and recommend ONE action.

POD: {pod_name}
NAMESPACE: {namespace}
STATUS: {pod_info['phase']} / {pod_info['container_state']}
RESTART COUNT: {pod_info['restart_count']}
IMAGE: {pod_info['image']}

EVENTS:
{events_text}

LOGS (last 50 lines):
{logs_text[:2000]}

Choose exactly ONE action:
- RESTART: Delete the pod (Deployment will recreate it). Use when: transient crash, OOMKilled after GC, random failure.
- ALERT: Do not act, alert humans. Use when: bad image tag, persistent config error, missing dependency.

Respond ONLY in this JSON format:
{{"root_cause": "one sentence", "action": "RESTART or ALERT", "confidence": "HIGH or MEDIUM or LOW", "explanation": "one sentence for the on-call engineer"}}"""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
    })

    response = bedrock.invoke_model(modelId=BEDROCK_MODEL, body=body)
    result = json.loads(response["body"].read())
    text = result["content"][0]["text"]

    # Parse JSON from response
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return {"root_cause": text, "action": "ALERT", "confidence": "LOW", "explanation": "Could not parse AI response"}


# ─── Execute Remediation ─────────────────────────────────────────────────────

def execute_action(action, pod_name, namespace):
    """Execute the recommended action."""
    if action == "RESTART":
        if AUTO_HEAL:
            log.info(f"  🔧 EXECUTING: Deleting pod {pod_name} (Deployment will recreate)")
            v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
            return "EXECUTED"
        else:
            log.info(f"  ⚠️  AUTO_HEAL disabled. Would restart {pod_name}")
            return "SKIPPED"
    else:
        log.info(f"  📢 ALERT: Human intervention needed for {pod_name}")
        return "ALERTED"


# ─── Verify After Action ─────────────────────────────────────────────────────

def verify_health(deployment_name, namespace, timeout=90):
    """Wait and check if the pod recovered."""
    log.info(f"  ⏳ Waiting 60s to verify health...")
    time.sleep(60)
    try:
        pods = v1.list_namespaced_pod(
            namespace=namespace, label_selector=f"app={deployment_name}"
        )
        for pod in pods.items:
            for cs in pod.status.container_statuses or []:
                if cs.ready:
                    log.info(f"  ✅ Pod {pod.metadata.name} is HEALTHY (Ready)")
                    return True
        log.warning(f"  ❌ Pod still not healthy after 60s")
        return False
    except Exception as e:
        log.error(f"  ❌ Verification failed: {e}")
        return False


# ─── Main Watch Loop ─────────────────────────────────────────────────────────

def watch_pods():
    """Main loop: watch for failing pods and heal them."""
    log.info("=" * 60)
    log.info("  ZEN PHARMA AIOps SELF-HEALING AGENT")
    log.info("=" * 60)
    log.info(f"  Watching namespace: {NAMESPACE}")
    log.info(f"  Bedrock model:      {BEDROCK_MODEL}")
    log.info(f"  Auto-heal:          {AUTO_HEAL}")
    log.info(f"  Check interval:     {CHECK_INTERVAL}s")
    log.info("=" * 60)

    while True:
        try:
            # List all pods in namespace
            pods = v1.list_namespaced_pod(namespace=NAMESPACE)

            for pod in pods.items:
                pod_name = pod.metadata.name
                # Skip agent itself
                if "aiops-agent" in pod_name:
                    continue

                # Check container statuses for failures
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
                        reason = f"RestartCount={cs.restart_count}"

                    if is_failing and not is_on_cooldown(pod_name):
                        mark_incident(pod_name)
                        log.info("")
                        log.info(f"  🚨 INCIDENT DETECTED")
                        log.info(f"  Pod:    {pod_name}")
                        log.info(f"  Reason: {reason}")
                        log.info(f"  Namespace: {NAMESPACE}")
                        log.info("")

                        # Gather context
                        log.info(f"  📋 Gathering context...")
                        events_text = get_pod_events(pod_name, NAMESPACE)
                        logs_text = get_pod_logs(pod_name, NAMESPACE)
                        pod_info = get_pod_info(pod_name, NAMESPACE)
                        log.info(f"  - Events: collected")
                        log.info(f"  - Logs: {'collected' if logs_text else 'empty'}")
                        log.info(f"  - Status: {pod_info['container_state']}, restarts: {pod_info['restart_count']}")
                        log.info("")

                        # Call Bedrock
                        log.info(f"  🧠 Calling AWS Bedrock ({BEDROCK_MODEL})...")
                        try:
                            analysis = call_bedrock(pod_name, NAMESPACE, events_text, logs_text, pod_info)
                            log.info(f"  ─── BEDROCK RESPONSE ───")
                            log.info(f"  Root Cause:  {analysis.get('root_cause', 'unknown')}")
                            log.info(f"  Action:      {analysis.get('action', 'ALERT')}")
                            log.info(f"  Confidence:  {analysis.get('confidence', 'LOW')}")
                            log.info(f"  Explanation: {analysis.get('explanation', '')}")
                            log.info(f"  ──────────────────────────")
                            log.info("")
                        except Exception as e:
                            log.error(f"  ❌ Bedrock call failed: {e}")
                            analysis = {"action": "ALERT", "root_cause": str(e)}

                        # Execute
                        action = analysis.get("action", "ALERT")
                        result = execute_action(action, pod_name, NAMESPACE)

                        # Verify if we took action
                        if result == "EXECUTED":
                            app_label = pod.metadata.labels.get("app", "")
                            if app_label:
                                verify_health(app_label, NAMESPACE)

                        log.info(f"  📊 Incident complete. Action={action}, Result={result}")
                        log.info("")

        except Exception as e:
            log.error(f"Watch loop error: {e}")

        time.sleep(CHECK_INTERVAL)


# ─── Health Endpoint (for liveness probe) ────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "healthy", "agent": "aiops"}).encode())

    def log_message(self, format, *args):
        pass  # suppress access logs


def start_health_server():
    server = HTTPServer(("0.0.0.0", 8000), HealthHandler)
    server.serve_forever()


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Start health endpoint in background
    health_thread = Thread(target=start_health_server, daemon=True)
    health_thread.start()
    log.info("Health endpoint started on :8000")

    # Start watching
    watch_pods()
