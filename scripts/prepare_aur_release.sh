#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-0.1.0}"
AUR_DIR="packaging/aur"

echo "==> Preparing AUR release for Showberry v${VERSION}..."

# Update version in PKGBUILD if different
sed -i "s/^pkgver=.*/pkgver=${VERSION}/" "${AUR_DIR}/PKGBUILD"

# Regenerate .SRCINFO
echo "==> Generating .SRCINFO..."
(cd "${AUR_DIR}" && makepkg --printsrcinfo > .SRCINFO)

echo "==> AUR package files ready in ${AUR_DIR}/:"
ls -la "${AUR_DIR}"

echo ""
echo "To publish to the AUR:"
echo "  1. git clone ssh://aur@aur.archlinux.org/showberry.git /tmp/showberry-aur"
echo "  2. cp packaging/aur/PKGBUILD packaging/aur/.SRCINFO /tmp/showberry-aur/"
echo "  3. cd /tmp/showberry-aur && git add PKGBUILD .SRCINFO && git commit -m 'Update to v${VERSION}' && git push"
