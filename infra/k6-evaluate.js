import { stages, thresholds } from 'k6';
import http from 'k6/http';
import { check } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 50 },
    { duration: '1m', target: 200 },
  ],
  thresholds: {
    http_req_duration: ['p(99)<5'],
    http_req_failed: ['rate<0.01'],
  },
};

export default function () {
  const res = http.post(
    'http://localhost/api/v1/flags/evaluate',
    JSON.stringify({ keys: ['new_checkout'], context: { user_id: `u-${__VU}-${__ITER}` } }),
    { headers: { 'Content-Type': 'application/json' } }
  );
  check(res, { 'status 200': (r) => r.status === 200 });
}
