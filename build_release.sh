#!/bin/bash
# Build script for creating a distributable iMessage Wrapped app

set -e  # Exit on error

echo "🚀 Building iMessage Wrapped..."

# Activate virtual environment
source venv/bin/activate

# Install/update PyInstaller
echo "📦 Installing PyInstaller..."
pip install pyinstaller --quiet

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf build dist

# Build the app
echo "🔨 Building app..."
pyinstaller imessage_wrapped.spec --clean

# Create a zip file for distribution
echo "📦 Creating distribution package..."
cd dist
zip -r "iMessage-Wrapped.zip" "iMessage Wrapped.app"
cd ..

echo "✅ Build complete!"
echo "📍 App location: dist/iMessage Wrapped.app"
echo "📦 Distribution package: dist/iMessage-Wrapped.zip"
echo ""
echo "To create a GitHub release:"
echo "1. Go to your GitHub repository"
echo "2. Click 'Releases' → 'Create a new release'"
echo "3. Upload dist/iMessage-Wrapped.zip"
echo "4. Users can download and unzip to get the app!"
