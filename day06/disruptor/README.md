# xk6-disruptor scenarios

Fault injection scripts for the demo-services cluster.
Targets are selected by pod label (`app=<service>`), so any service deployed
with the conventional label scheme can be targeted without script changes.

## Install xk6-disruptor

Two ways — pick whichever fits:

**a) Standalone CLI binary** (recommended for a clean demo):

```bash
# https://github.com/grafana/xk6-disruptor/releases
curl -fsSL https://github.com/grafana/xk6-disruptor/releases/latest/download/xk6-disruptor-linux-amd64.tar.gz \
  | tar -xz -C /tmp
sudo mv /tmp/xk6-disruptor /usr/local/bin/
```

**b) Build a k6 binary that bundles the extension**:

```bash
go install go.k6.io/xk6/cmd/xk6@latest
xk6 build --with github.com/grafana/xk6-disruptor
```

## Run a scenario

```bash
# Cluster must already be up (../scripts/up.sh).
xk6-disruptor run --kubeconfig ~/.kube/config disruptor/payment-latency.js
```

`payment-latency.js` injects 500ms latency on every request to
`payment-service` for 60 seconds while a small load generator hits
`/charge` at 20 rps. Open Grafana at <http://localhost:3001> and watch:

```promql
histogram_quantile(0.95,
  sum by (le, git_version) (rate(payment_charge_duration_seconds_bucket[1m]))
)
```

The p95 line should jump at the start of the run and recover when it ends.
That spike, joined to the `git_version` label, is what the AIOps agent's
planner+executor will be asked to root-cause.

## Adding new scenarios

The scripts live in this folder. Convention:

- `<service>-<fault-type>.js` (e.g. `payment-error-rate.js`,
  `payment-pod-kill.js`)
- Target pods by `{app=<service>}` label so scenarios are reusable
  across deployments
- Stick to one fault per script — combine scenarios at run time, not
  in the script body
