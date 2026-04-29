#!/bin/sh
# FileMorph one-click starter for Linux / macOS
set -e

echo ""
echo " ================================================================"
echo "  FileMorph - File Converter & Compressor"
echo " ================================================================"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo " ERROR: Docker is not running."
    echo ""
    echo " Please start Docker and run this script again."
    echo "   Linux:  sudo systemctl start docker"
    echo "   macOS:  open Docker Desktop"
    echo ""
    exit 1
fi

echo " Docker is running. Starting FileMorph..."
echo ""

# Start the container
docker compose up -d --build

echo ""
echo " Waiting for FileMorph to be ready..."

# Poll until healthy (max ~2 minutes)
attempts=0
while true; do
    attempts=$((attempts + 1))
    if [ "$attempts" -gt 40 ]; then
        echo ""
        echo " Timeout: FileMorph did not start within 2 minutes."
        echo " Check logs with: docker compose logs filemorph"
        exit 1
    fi

    if docker compose ps filemorph 2>/dev/null | grep -q "healthy"; then
        break
    fi
    sleep 3
done

echo " FileMorph is ready!"
echo ""

# Show API key if first run
echo " ================================================================"
docker compose logs --tail=30 filemorph 2>&1 | grep "API KEY" || true
echo " ================================================================"
echo ""
echo " Web UI:  http://localhost:8000"
echo " API:     http://localhost:8000/docs"
echo ""
echo " To stop FileMorph: docker compose down"
echo ""

# Open browser
if command -v xdg-open > /dev/null 2>&1; then
    xdg-open http://localhost:8000
elif command -v open > /dev/null 2>&1; then
    open http://localhost:8000
fi
