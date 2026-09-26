FROM node:24-alpine AS development

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev"]

FROM development AS build
RUN npm run build

FROM nginx:1.29-alpine AS production
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80

