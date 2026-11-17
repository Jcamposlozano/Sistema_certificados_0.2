# syntax=docker/dockerfile:1
FROM node:22.23.1-bookworm-slim AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY angular.json tsconfig*.json ./
COPY public/ ./public/
COPY src/ ./src/
ENV NG_CLI_ANALYTICS=false
RUN npm run build

FROM nginx:stable-alpine

COPY nginx-beta.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/ucts-zone/browser/ /usr/share/nginx/html/
EXPOSE 8080
