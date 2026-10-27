# Orchestrator test image plus a Node toolchain for TypeScript tasks.
# Repos without their own node_modules borrow /opt/tsdeps/node_modules (see orch/langs.py).
FROM node:22.11.0-bookworm-slim AS node
FROM langgraph-orchestrator:orch-test
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && mkdir -p /opt/tsdeps && cd /opt/tsdeps && npm init -y >/dev/null \
 && npm install --no-audit --no-fund typescript@5.6.3 vitest@2.1.9 @types/node@20.17.6 \
 && node --version && node_modules/.bin/tsc --version && node_modules/.bin/vitest --version
ENV ORCH_NODE_MODULES=/opt/tsdeps/node_modules
