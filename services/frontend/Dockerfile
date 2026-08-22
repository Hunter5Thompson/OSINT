FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

ARG VITE_SPATIAL_SCOPE_ENABLED=true
ENV VITE_SPATIAL_SCOPE_ENABLED=$VITE_SPATIAL_SCOPE_ENABLED

COPY . .
RUN npm run build

FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html

# Nginx config for SPA routing + cache headers (see nginx.conf)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 5173

CMD ["nginx", "-g", "daemon off;"]
