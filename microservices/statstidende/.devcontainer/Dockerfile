FROM mcr.microsoft.com/devcontainers/python:3.12-bookworm

WORKDIR /workspace

# Install FastAPI & Uvicorn
RUN pip install --no-cache-dir fastapi uvicorn httpx python-dotenv requests dotenv

# Copy the local code into the container
# (VS Code also mounts it live, so this helps for build-time commands)
COPY . .

# Ensure vscode user exists and owns workspace
RUN id vscode 2>/dev/null || useradd -ms /bin/bash vscode
RUN chown -R vscode:vscode /workspace

# Expose the FastAPI port
EXPOSE 8000

# Run the FastAPI app on container startup
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]

