FROM oven/bun:1

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY src ./src

ENV PORT=4000
EXPOSE 4000

# Probes /health rather than the TCP port. A process that bound its port but
# failed boot validation is listening and broken at the same time, and a port
# probe cannot tell those apart. 503 from /health is what marks the container
# unhealthy, which is the signal depends_on: service_healthy waits on.
#
# No curl in the base image, and bun is already here, so it does the fetch.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=3 \
  CMD bun -e "const r = await fetch('http://127.0.0.1:' + (process.env.PORT ?? 4000) + '/health'); process.exit(r.ok ? 0 : 1)"

CMD ["bun", "run", "src/index.ts"]
