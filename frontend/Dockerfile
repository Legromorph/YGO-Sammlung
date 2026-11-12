# npm install and the Next.js build run natively on the build host
# ($BUILDPLATFORM). Their output is plain JavaScript, so only the small runtime
# stage is assembled per target platform. This keeps the multi-arch CI build
# from running the heavy Next.js build under slow, crash-prone QEMU emulation.
FROM --platform=$BUILDPLATFORM node:20-alpine AS deps

WORKDIR /app

COPY package*.json ./
RUN npm ci

FROM --platform=$BUILDPLATFORM node:20-alpine AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build
# sharp is a native binary for the build host only; the app does not use
# next/image (images.unoptimized), so it is not shipped.
RUN rm -rf .next/standalone/node_modules/@img .next/standalone/node_modules/sharp

FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000

CMD ["node", "server.js"]
