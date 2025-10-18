#!/bin/bash

echo "Checking Talos API setup (Python 3.12)..."

# Check required directories
echo "Verifying directory structure..."
DIRS=(
    "src/api"
    "src/api/model"
    "src/api/router"
    "src/api/service"
    "src/api/repository"
    "src/api/middleware"
    "src/api/util"
    "logs"
)

for dir in "${DIRS[@]}"; do
    if [ -d "$dir" ]; then
        echo " $dir"
    else
        echo " $dir (missing)"
        mkdir -p "$dir"
        echo "    Created"
    fi
done

# Check core files
echo ""
echo "Verifying core files..."
FILES=(
    "src/api/app.py"
    "src/api/lifecycle.py"
    "src/api/dependency.py"
    "src/api/model/requests.py"
    "src/api/model/responses.py"
    "src/api/model/enums.py"
    "src/api/router/devices.py"
    "src/api/router/parameters.py"
    "src/api/router/batch.py"
    "src/api/router/monitoring.py"
    "src/api/router/health.py"
    "src/api/service/device_service.py"
    "src/api/service/parameter_service.py"
    "src/api/repository/modbus_repository.py"
    "src/api/repository/config_repository.py"
    "src/api/middleware/error_handler.py"
    "src/api/middleware/logging_middleware.py"
    "src/api/util/logging_config.py"
)

MISSING_COUNT=0
for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        echo " $file"
    else
        echo " $file (missing)"
        ((MISSING_COUNT++))
    fi
done

# Check config files
echo ""
echo "Verifying configuration files..."
CONFIG_FILES=(
    "res/modbus_device.yml"
    "res/device_instance_config.yml"
)

for file in "${CONFIG_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo " $file"
    else
        echo " $file (missing - Talos configuration required)"
        ((MISSING_COUNT++))
    fi
done

# Check Python version
echo ""
echo "Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "   Current version: $PYTHON_VERSION"

# Check Python dependencies
echo ""
echo "Verifying Python dependencies..."
DEPS=("fastapi" "uvicorn" "pydantic" "pymodbus" "yaml")
for dep in "${DEPS[@]}"; do
    python3 -c "import $dep" 2>/dev/null && echo " $dep" || {
        echo " $dep (needs to be installed)"
        ((MISSING_COUNT++))
    }
done

echo ""
if [ $MISSING_COUNT -eq 0 ]; then
    echo "All checks passed! Ready to start the service."
    exit 0
else
    echo "Found $MISSING_COUNT issue(s). Please resolve them first."
    exit 1
fi
