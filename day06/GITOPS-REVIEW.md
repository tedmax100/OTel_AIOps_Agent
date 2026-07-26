# Reviewing a PR against `k8s/`

This is not a YAML-syntax checklist — `kubectl kustomize` (or CI running the
same command) already fails loudly on syntax errors and unknown fields. What
it does **not** catch is a change that is syntactically valid but silently
changes what gets observed. That's what a human reviewer is for.

Before approving a PR that touches `k8s/`, check:

1. **Does this PR add or rename a Deployment without also touching
   `16-instrumentation.yaml` or its Pod annotation?**
   A new service with no `instrumentation.opentelemetry.io/inject-python`
   annotation deploys fine, passes readiness/liveness probes, serves
   traffic — and emits zero traces. Nothing in `kubectl apply` output or
   `kubectl get pods` tells you that. Diff the annotations block, not just
   the container spec.

2. **Does this PR rename a label the Instrumentation CR or a Service
   selector depends on?**
   `23-api-gateway.yaml`'s `git_version` pod label feeds
   `OTEL_RESOURCE_ATTRIBUTES` through the Downward API — renaming it without
   updating the `fieldRef` doesn't error at apply time, it silently drops
   `service.version` from every span's resource attributes going forward.

3. **Does this PR change `13-otel-collector.yaml`'s resource limits?**
   Day4 showed collector `OOMKilled` under-provisioning fails silently from
   the app's point of view (no exporter error — spans just never arrive
   downstream). A resource-limit change here deserves the same scrutiny as
   a code change to the collector, not a rubber-stamp because "it's just a
   YAML number."

4. **Does the exporter endpoint in `16-instrumentation.yaml` still match the
   Service name/namespace in `13-otel-collector.yaml`?**
   These two files reference each other by string
   (`http://otel-collector.demo.svc:4318`) with nothing to statically
   enforce the link. A rename on one side without the other is a valid
   `kustomize build` and a valid `kubectl apply` — and a cluster where every
   auto-instrumented service silently fails to export.

5. **Is the diff scoped to what the PR claims to do?**
   Because `kustomization.yaml` resolves the whole `resources` list into one
   stream, `kubectl kustomize k8s/ | kubectl diff -f -` against the live
   cluster shows the *actual* blast radius of a PR — including resources the
   PR didn't mean to touch (e.g. a `commonLabels` addition stamping every
   resource, not just the one the author intended). Run that diff, don't
   just read the file-level PR diff.

None of this is enforced by a schema. It's the list of "looks like a no-op,
isn't" changes this stack has already produced once (Day4's collector
OOMKilled) or could easily produce next (a new service missing its
annotation). The checklist exists because `kubectl apply` succeeding is not
the same claim as "traces still flow."
