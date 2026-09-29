FROM oven/bun:1

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY src ./src

ENV PORT=4000
EXPOSE 4000

CMD ["bun", "run", "src/index.ts"]
