#!/usr/bin/env bash
# Network plumbing for jobseeker on minikube, from inside the sandbox. Run after every
# `minikube start` and sandbox restart (none of this survives one). Idempotent.
#
# 1. The node's FORWARD chain defaults to DROP (left by Docker in the kicbase image), so
#    pods can't open any connection beyond the node, not even DNS. Set it to ACCEPT.
# 2. Pods can't reach the sandbox proxy (gateway.docker.internal) themselves. Relay it on
#    the sandbox's address in minikube's network: pods use http://<gateway>:3128.
# 3. The browser: relay sandbox port $JOBSEEKER_PORT (default 8090, the port `sbx ports`
#    publishes) to the jobseeker Service's node port 30090.
set -euo pipefail

gateway=$(docker network inspect minikube --format '{{(index .IPAM.Config 0).Gateway}}')
port=3128

minikube ssh -- sudo iptables -P FORWARD ACCEPT
echo "minikube node: FORWARD policy ACCEPT"

if (exec 3<>"/dev/tcp/$gateway/$port") 2>/dev/null; then
  echo "relay already listening on $gateway:$port"
else
  proxy=${HTTPS_PROXY:-${https_proxy:?no HTTPS_PROXY set: is this the sandbox?}}
  hostport=${proxy#*://}; hostport=${hostport%/}
  host=${hostport%:*}; upstream_port=${hostport##*:}
  # the sandbox reaches its proxy over IPv6; `getent hosts` lists that address first
  addr=$(getent hosts "$host" | awk '{print $1; exit}')
  if [[ $addr == *:* ]]; then target="TCP6:[$addr]:$upstream_port"; else target="TCP4:$addr:$upstream_port"; fi
  setsid nohup socat "TCP4-LISTEN:$port,bind=$gateway,reuseaddr,fork" "$target" \
    > /tmp/jobseeker-relay.log 2>&1 < /dev/null &
  sleep 1
  (exec 3<>"/dev/tcp/$gateway/$port") 2>/dev/null || { echo "relay did not start, see /tmp/jobseeker-relay.log"; exit 1; }
  echo "relay $gateway:$port -> $host:$upstream_port ($target), pid $!"
fi

web_port=${JOBSEEKER_PORT:-8090}
node_ip=$(minikube ip)
if (exec 3<>"/dev/tcp/127.0.0.1/$web_port") 2>/dev/null; then
  if pgrep -f "TCP4-LISTEN:$web_port,.*TCP4:$node_ip:30090" > /dev/null; then
    echo "web relay already listening on :$web_port"
  else
    echo "port $web_port is taken by something else (a local jobseeker serve?): no web relay;"
    echo "stop that, or use another port: JOBSEEKER_PORT=8091 $0"
  fi
else
  setsid nohup socat "TCP4-LISTEN:$web_port,reuseaddr,fork" "TCP4:$node_ip:30090" \
    > /tmp/jobseeker-web-relay.log 2>&1 < /dev/null &
  sleep 1
  echo "web relay :$web_port -> $node_ip:30090 (jobseeker Service), pid $!"
fi

if [[ $gateway != 192.168.49.1 ]]; then
  echo "note: deploy/k8s/jobseeker.yaml expects the proxy at 192.168.49.1:$port; update HTTPS_PROXY/HTTP_PROXY there"
fi
