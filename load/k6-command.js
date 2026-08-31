import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  vus: Number(__ENV.VUS || 10),
  duration: __ENV.DURATION || "30s",
  thresholds: { http_req_failed: ["rate<0.01"], http_req_duration: ["p(95)<500"] },
};

const base = __ENV.BASE_URL || "http://127.0.0.1:8000";
const auth = __ENV.AUTHORIZATION ? { Authorization: __ENV.AUTHORIZATION } : {};
const dev = __ENV.DEV_IDENTITY === "operator" ? { "X-Dev-Identity": "operator" } : {};
const readHeaders = { headers: { ...auth, ...dev, "X-Correlation-ID": `k6-${__VU}-${__ITER}` } };

export default function () {
  check(http.get(`${base}/api/v1/command/summary`, readHeaders), { "summary readable": (response) => response.status === 200 });
  check(http.get(`${base}/api/v1/updates?limit=50`, readHeaders), { "updates readable": (response) => response.status === 200 });
  if (__ITER % 5 === 0) {
    const key = `k6-${__VU}-${__ITER}`;
    const response = http.post(`${base}/api/v1/response-queue`, JSON.stringify({ title: `synthetic load ${key}`, priority: "normal" }), { headers: { ...auth, ...dev, "Content-Type": "application/json", "X-Correlation-ID": key, "Idempotency-Key": key } });
    check(response, { "mutation reconciled": (value) => [200, 201, 409].includes(value.status) });
  }
  sleep(1);
}
