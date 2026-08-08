# Next.js 16 frontend.
#
# docker-compose.yml referenced this file for months and it did not exist, so
# `docker compose up` failed at build and had evidently never been run.
#
# Three stages: deps, build, run. The point of the split is that the runtime
# image carries neither the toolchain nor the source.

# ---------------------------------------------------------------------------
# deps
# ---------------------------------------------------------------------------
FROM node:22-alpine AS deps
WORKDIR /app

# --include=dev is deliberate, and the same reasoning as frontend/render.yaml:
# typescript, tailwindcss and babel-plugin-react-compiler are devDependencies
# and are required to BUILD. If NODE_ENV=production leaks into the build
# environment a bare `npm ci` skips them and the build fails.
#
# `npm ci` rather than `npm install`: clsx and three @radix-ui packages are
# imported but not declared in package.json, and resolve only as hoisted
# transitives from the committed lockfile. `npm install` may re-resolve and
# break the build.
COPY package.json package-lock.json ./
RUN npm ci --include=dev

# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Guarantee public/ exists before the run stage copies it.
#
# The run stage does `COPY --from=build /app/public ./public`, and Docker's
# COPY fails the whole build when its source does not exist. git cannot track
# an empty directory, so public/ is only present because some file inside it
# is committed -- which made the image build depend on that, silently. Deleting
# the last file in public/ would have broken `docker build` while leaving
# `next build` perfectly green, and the error names a COPY rather than the
# deletion that caused it.
#
# One line here means the build no longer cares either way.
RUN mkdir -p public

# NEXT_PUBLIC_* is inlined into the client bundle at BUILD time, not read at
# runtime. That is why these are build args rather than container env: setting
# them in `docker run` has no effect whatsoever, which is the single most
# common way to deploy this frontend pointing at localhost:8000.
#
# Both names are required. Eight components read NEXT_PUBLIC_API_URL while
# dashboard/AnomalyDetection.tsx and dashboard/StockPredictions.tsx read
# NEXT_PUBLIC_API_BASE; setting only one leaves those two panels talking to
# localhost in production, and it surfaces as an opaque CORS error rather than
# anything that names the cause.
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_API_BASE
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------
FROM node:22-alpine AS run
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000

# Not root. The Node image ships a `node` user; use it rather than minting one.
USER node

# `output: "standalone"` in next.config.ts produces .next/standalone with a
# self-contained server.js and only the node_modules it actually needs. Without
# it this stage would have to copy the whole 1 GB+ node_modules tree.
#
# static/ and public/ are NOT included in standalone and must be copied
# separately -- miss them and the app serves HTML with no CSS or JS, which
# looks like a broken build rather than a missing COPY.
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public

EXPOSE 3000

# server.js, not `next start`: the standalone output is its own server and the
# next CLI is not present in this stage.
CMD ["node", "server.js"]
