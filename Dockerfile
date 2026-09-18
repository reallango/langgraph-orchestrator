FROM python:3.11

ARG PWSH_VERSION=7.4.6

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

# Base packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    less \
    nano \
    libicu72 \
    && rm -rf /var/lib/apt/lists/*

# PowerShell
RUN mkdir -p /opt/microsoft/powershell/7 && \
    curl -sSL \
    "https://github.com/PowerShell/PowerShell/releases/download/v${PWSH_VERSION}/powershell-${PWSH_VERSION}-linux-x64.tar.gz" \
    -o /tmp/powershell.tar.gz && \
    tar -xzf /tmp/powershell.tar.gz -C /opt/microsoft/powershell/7 && \
    chmod +x /opt/microsoft/powershell/7/pwsh && \
    ln -s /opt/microsoft/powershell/7/pwsh /usr/bin/pwsh && \
    rm /tmp/powershell.tar.gz

# PowerShell tooling
RUN pwsh -NoLogo -NonInteractive -Command \
    "Set-PSRepository -Name PSGallery -InstallationPolicy Trusted; \
     Install-Module -Name PSScriptAnalyzer -Scope AllUsers -Force"

# Python dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Git defaults
RUN git config --system user.email "aider@ai-nuc.local" && \
    git config --system user.name "Aider" && \
    git config --system --add safe.directory '*'

WORKDIR /app

CMD ["bash"]
