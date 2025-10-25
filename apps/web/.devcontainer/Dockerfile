FROM mcr.microsoft.com/devcontainers/typescript-node:22-bookworm

# Enable pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# Work in project directory
WORKDIR /workspace

# Copy dependencies first for caching
COPY package*.json ./
COPY pnpm-lock.yaml* ./

# Fix file permission issues for non-root installs
USER root
RUN mkdir -p /workspace && chown -R node:node /workspace
USER node

# Install dependencies
RUN pnpm install --frozen-lockfile --prefer-offline || pnpm rebuild @next/swc-linux-arm64-gnu

# Copy source
COPY . .

EXPOSE 3000
CMD ["pnpm", "dev"]
