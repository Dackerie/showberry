# Showberry 🍓: Distribution & Publishing Guide

This guide details how to publish and distribute **Showberry** to Linux users worldwide through **GitHub**, **Flathub**, and the **Arch User Repository (AUR)**.

---

## Architecture & Ecosystem Overview

```
[Local Codebase] 
      │
      ├──> [GitHub Repository] 
      │           │
      │           ├──> [GitHub Releases] (Source tarballs, .whl)
      │           │           │
      │           │           ├──> [Flathub Submission] ──> GNOME Software & KDE Discover (All Distros)
      │           │           │
      │           │           └──> [AUR Submission] ────> yay / paru (Arch, EndeavourOS, Manjaro)
      │           │
      │           └──> [GitHub Actions CI/CD] (Automated test & validation suite)
```

---

## Stage 1: Publishing to GitHub

Since Showberry does not yet have a remote git repository, the first step is pushing the project to GitHub.

### 1. Create the GitHub Repository
1. Open your browser and navigate to **[github.com/new](https://github.com/new)**.
2. Enter Repository name: `showberry`.
3. Set Visibility to **Public**.
4. **Important**: Leave "Add a README file", "Add .gitignore", and "Choose a license" **unchecked** (we already have clean, customized files in the repo).
5. Click **Create repository**.

### 2. Push Your Local Commits
In your terminal inside `/home/vishwam/code/showberry`:

```bash
# If using SSH (recommended):
git remote add origin git@github.com:<YOUR_GITHUB_USERNAME>/showberry.git

# Or if using HTTPS:
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/showberry.git

# Push master branch
git branch -M master
git push -u origin master
```

### 3. Tag and Release Version 0.1.0
Create an official annotated git tag for the initial release:

```bash
git tag -a v0.1.0 -m "Showberry v0.1.0: Initial public release"
git push origin v0.1.0
```

Once pushed, GitHub Actions (`.github/workflows/release.yml`) will automatically:
- Build the Python wheel (`.whl`) and source tarball (`.tar.gz`).
- Calculate SHA256 checksums.
- Create an official GitHub Release with release assets attached.

---

## Stage 2: Publishing to Flathub (Universal Linux App Store)

Flathub is the standard app distribution platform for the Linux desktop, enabling 1-click installs across Ubuntu, Fedora, Debian, Arch, openSUSE, and SteamOS.

### Prerequisites
- Your GitHub repository is public and tagged with `v0.1.0`.
- Your release archive URL is accessible:
  `https://github.com/<YOUR_GITHUB_USERNAME>/showberry/archive/refs/tags/v0.1.0.tar.gz`

### Step-by-Step Flathub Submission
1. **Fork the Flathub Repository**:
   - Go to [github.com/flathub/flathub](https://github.com/flathub/flathub) and click **Fork**.

2. **Clone your fork locally**:
   ```bash
   git clone git@github.com:<YOUR_GITHUB_USERNAME>/flathub.git /tmp/flathub-submission
   cd /tmp/flathub-submission
   git checkout -b add-showberry
   ```

3. **Prepare the Manifest**:
   Calculate the SHA256 of your release tarball:
   ```bash
   curl -sL "https://github.com/<YOUR_GITHUB_USERNAME>/showberry/archive/refs/tags/v0.1.0.tar.gz" | sha256sum
   ```
   Update `packaging/flathub/io.github.Dackerie.Showberry.json`:
   - Replace `<YOUR_GITHUB_USERNAME>` with your GitHub username.
   - Replace `PLACEHOLDER_SHA256` with the calculated hash.

4. **Add and Commit the Manifest**:
   ```bash
   cp /home/vishwam/code/showberry/packaging/flathub/io.github.Dackerie.Showberry.json .
   git add io.github.Dackerie.Showberry.json
   git commit -m "Add io.github.Dackerie.Showberry"
   git push -u origin add-showberry
   ```

5. **Submit the Pull Request**:
   - Go to your fork on GitHub and click **Compare & pull request** against `flathub/flathub:master`.
   - Title: `Add io.github.Dackerie.Showberry`
   - Description: Brief summary explaining Showberry and linking to your upstream repository.
   - The `@flathubbot` will trigger test builds for `x86_64` and `aarch64`.
   - Once approved by Flathub reviewers, they will merge the PR and invite you to the newly created `flathub/io.github.Dackerie.Showberry` repository.

### How Users Install via Flatpak
Once published on Flathub:
```bash
# Command line:
flatpak install flathub io.github.Dackerie.Showberry
flatpak run io.github.Dackerie.Showberry

# GUI:
# Users can simply search "Showberry" inside GNOME Software, KDE Discover, or Flathub.org!
```

---

## Stage 3: Publishing to the AUR (Arch Linux / EndeavourOS / Manjaro)

The Arch User Repository (AUR) allows any Arch-based Linux user to install Showberry with standard AUR helpers like `yay` or `paru`.

### 1. Set Up Your AUR Account
1. Register an account at **[aur.archlinux.org/register](https://aur.archlinux.org/register)**.
2. In your AUR Account Profile, paste your SSH public key (`cat ~/.ssh/id_ed25519.pub`).

### 2. Clone the AUR Package Repository
Every AUR package is its own git repository hosted on `aur.archlinux.org`:

```bash
git clone ssh://aur@aur.archlinux.org/showberry.git /tmp/showberry-aur
```

### 3. Generate Package Files
Run the helper script from the Showberry repo:

```bash
./scripts/prepare_aur_release.sh 0.1.0
```

Copy the generated files into your cloned AUR directory:

```bash
cp packaging/aur/PKGBUILD /tmp/showberry-aur/
cp packaging/aur/.SRCINFO /tmp/showberry-aur/
```

### 4. Commit and Push to the AUR
```bash
cd /tmp/showberry-aur
git add PKGBUILD .SRCINFO
git commit -m "Initial release v0.1.0"
git push origin master
```

**That's it!** Showberry is immediately live on the AUR.

### How Users Install via AUR
```bash
yay -S showberry
# or
paru -S showberry
```

---

## Summary of Commands for Quick Reference

| Action | Command |
| :--- | :--- |
| **Add Remote** | `git remote add origin git@github.com:<user>/showberry.git` |
| **Push Code** | `git push -u origin master` |
| **Push Release Tag** | `git tag -a v0.1.0 -m "v0.1.0" && git push origin v0.1.0` |
| **Prepare AUR Files** | `./scripts/prepare_aur_release.sh 0.1.0` |
| **Test Local Build** | `makepkg -f` |
