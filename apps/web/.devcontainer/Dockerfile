# Use Microsoft’s Dev Container Node base image
FROM mcr.microsoft.com/devcontainers/typescript-node:20

WORKDIR /workspace

# Enable corepack (ships with Node)
RUN corepack enable \
    && corepack prepare pnpm@10.19.0 --activate

# Copy lockfile and manifest first (for build cache)
COPY . .

# Install dependencies using pnpm
RUN pnpm install --frozen-lockfile

# Copy project files
COPY . .

# Expose web port
EXPOSE 3000

# Default command for dev mode (can override in compose)
CMD ["pnpm", "dev"]
