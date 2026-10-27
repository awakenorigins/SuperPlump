FROM node:22-slim
WORKDIR /srv
COPY api/package*.json ./api/
RUN cd api && npm install --omit=dev
COPY api ./api
COPY admin ./admin
COPY prototype ./prototype
COPY legal ./legal
ENV NODE_ENV=production PORT=8386 ALLOW_DEV_UUID=0
EXPOSE 8386
CMD ["node","api/server.js"]
