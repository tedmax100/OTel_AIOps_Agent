// Inject 500ms latency on 30% of requests to payment-service for 60s.
//
// Run with:
//   xk6-disruptor run --kubeconfig ~/.kube/config disruptor/payment-latency.js
// or, if you have the xk6 binary built with the disruptor extension:
//   xk6 run disruptor/payment-latency.js
//
// Targets pods by label (app=payment-service). Once the run ends, the
// disruptor removes the injected proxy and traffic returns to baseline.

import { PodDisruptor } from "k6/x/disruptor";
import http from "k6/http";

export const options = {
  scenarios: {
    inject: {
      executor: "shared-iterations",
      iterations: 1,
      vus: 1,
      exec: "inject",
    },
    load: {
      executor: "constant-arrival-rate",
      rate: 20,
      timeUnit: "1s",
      duration: "60s",
      preAllocatedVUs: 5,
      exec: "load",
    },
  },
};

export function inject() {
  const selector = {
    namespace: "demo",
    select: { labels: { app: "payment-service" } },
  };
  const disruptor = new PodDisruptor(selector);
  disruptor.injectHTTPFaults(
    {
      averageDelay: "500ms",
      errorRate: 0.0,
      errorCode: 0,
    },
    "60s",
  );
}

export function load() {
  // NodePort exposed by k3d → host:8001
  http.post(
    "http://localhost:8001/charge",
    JSON.stringify({
      order_id: `o-${__VU}-${__ITER}`,
      user_id: `u-${__VU}`,
      amount_cents: 1000 + __ITER,
    }),
    { headers: { "Content-Type": "application/json" } },
  );
}
