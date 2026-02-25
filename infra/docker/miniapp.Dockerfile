FROM node:20-alpine
WORKDIR /miniapp
COPY package*.json ./
RUN npm install
COPY . .
