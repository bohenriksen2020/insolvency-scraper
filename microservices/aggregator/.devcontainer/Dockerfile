FROM mcr.microsoft.com/devcontainers/python:3.12-bookworm

SHELL ["/bin/bash", "-c"]
WORKDIR /workspace

RUN id vscode 2>/dev/null || useradd -ms /bin/bash vscode

ENTRYPOINT ["/bin/bash", "-l"]
