FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

ARG VITE_SPATIAL_SCOPE_ENABLED=true
ENV VITE_SPATIAL_SCOPE_ENABLED=$VITE_SPATIAL_SCOPE_ENABLED
ARG ODIN_BUILD_REVISION=unknown

COPY . .
RUN npm run build

FROM nginx:alpine@sha256:df221db836e1754089190208cee7eeda94f233197056426eda74a43ab1abeac2

ARG ODIN_BUILD_REVISION=unknown
LABEL org.opencontainers.image.revision=$ODIN_BUILD_REVISION

COPY --from=builder /app/dist /usr/share/nginx/html

# Nginx config for SPA routing + cache headers (see nginx.conf)
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY operator-gateway/ /opt/odin/operator-gateway/
COPY docker-entrypoint.d/ /docker-entrypoint.d/
RUN chmod +x /docker-entrypoint.d/40-odin-operator-gateway.sh

EXPOSE 5173

CMD ["nginx", "-g", "daemon off;"]
