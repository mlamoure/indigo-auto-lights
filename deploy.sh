#!/bin/bash
set -euo pipefail

# Variables (adjust paths if necessary)
SRC="/Users/mike/Mike's Sync Documents/Programming/indigo-auto-lights-plugin/Auto Lights.indigoPlugin"
NAME=$(basename "$SRC")
TMPDIR=$(mktemp -d)
TARGET_DIR="/Volumes/Perceptive Automation"

echo "Copying '$SRC' to a temporary directory: $TMPDIR"
cp -R "$SRC" "$TMPDIR"

echo "Cleaning the package: removing the 'Packages' subdirectory if it exists..."
rm -rf "$TMPDIR/$NAME/Packages"

echo "Removing any existing package named '$NAME' in the network location: $TARGET_DIR"
rm -rf "$TARGET_DIR/$NAME"

echo "Copying the cleaned package to the network location..."
cp -R "$TMPDIR/$NAME" "$TARGET_DIR"

echo "Cleaning up temporary files..."
rm -rf "$TMPDIR"

echo "Deployment complete."
