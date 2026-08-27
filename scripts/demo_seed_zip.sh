#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
zip -r /tmp/knowledgedesk-sample-docs.zip sample_docs >/dev/null
cat <<'EOF'
Created /tmp/knowledgedesk-sample-docs.zip
Upload it from the UI or via API:

curl -X POST http://localhost:8000/api/documents/upload-zip \
  -H 'X-Tenant-Key: kd-demo-key' \
  -F 'archive=@/tmp/knowledgedesk-sample-docs.zip' \
  -F 'department=Company Ops' \
  -F 'confidentiality=internal' \
  -F 'tags=demo,policies'
EOF
