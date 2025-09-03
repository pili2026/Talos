#!/usr/bin/env bash
set -euo pipefail

PYVER="3.12.5"
SWAPFILE="/etc/dphys-swapfile"
BACKUP="/tmp/swapfile.backup.$(date +%s)"

echo "==> Step 1: Check/Install build dependencies"
sudo apt update
sudo apt install -y build-essential zlib1g-dev libncurses5-dev libgdbm-dev \
  libnss3-dev libssl-dev libreadline-dev libffi-dev libsqlite3-dev libbz2-dev \
  wget curl ca-certificates dphys-swapfile

echo "==> Step 2: Temporarily increase swap to 2GB (to avoid crashes during build)"
if [ -f "$SWAPFILE" ]; then
  sudo cp "$SWAPFILE" "$BACKUP"
  sudo sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' "$SWAPFILE"
  sudo dphys-swapfile swapoff || true
  sudo dphys-swapfile setup
  sudo dphys-swapfile swapon
  echo "Swap increased to 2GB, original config backed up at $BACKUP"
fi

echo "==> Step 3: Download Python $PYVER source"
cd /usr/src
sudo rm -rf "Python-${PYVER}" "Python-${PYVER}.tgz"
sudo wget "https://www.python.org/ftp/python/${PYVER}/Python-${PYVER}.tgz"
sudo tar xzf "Python-${PYVER}.tgz"
cd "Python-${PYVER}"

echo "==> Step 4: Compile (use 2 cores to avoid Pi overheating/freezing)"
sudo ./configure --enable-optimizations
sudo make -j2
sudo make altinstall    # Install to /usr/local/bin/python3.12, without overwriting system python3

echo "==> Step 5: Verify Python version"
python3.12 --version || true

echo "==> Step 6: Create venv (~/py312-venv)"
if [ ! -d "$HOME/py312-venv" ]; then
  python3.12 -m venv "$HOME/py312-venv"
  echo "✅ Created ~/py312-venv"
fi

echo "==> Step 7: Restore original swap settings"
if [ -f "$BACKUP" ]; then
  sudo mv "$BACKUP" "$SWAPFILE"
  sudo dphys-swapfile swapoff || true
  sudo dphys-swapfile setup
  sudo dphys-swapfile swapon
  echo "Swap settings restored"
fi

echo
echo "✅ Done! Usage:"
echo "   source ~/py312-venv/bin/activate"
echo "   python --version"
