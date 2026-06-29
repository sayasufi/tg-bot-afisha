FROM node:20-alpine
WORKDIR /admin
COPY package*.json ./
RUN npm install
COPY . .
